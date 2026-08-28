import logging
import time

import httpx
import jwt
from fastapi import Depends, HTTPException, Query, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.config import settings
from app.database import get_session

logger = logging.getLogger("kio.auth")

_bearer = HTTPBearer(auto_error=False)
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Asymmetric algorithms Authentik can sign with (RSA or EC signing key).
_OIDC_ALGORITHMS = ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"]
_DEV_ALGORITHM = "HS256"

# kid -> public key object, populated at startup and refreshed on unknown kid
_jwks: dict = {}
# Unknown-kid refreshes are throttled so a flood of garbage tokens can't turn
# the API into a JWKS-fetching DoS amplifier against Authentik.
_JWKS_MIN_REFRESH_INTERVAL = 60.0
_jwks_last_refresh = 0.0


def oidc_enabled() -> bool:
    return bool(settings.authentik_issuer)


def dev_login_enabled() -> bool:
    return bool(settings.dev_username and settings.dev_password)


async def refresh_jwks(force: bool = True) -> None:
    """Fetch Authentik's signing keys via OIDC discovery.

    force=False skips the fetch when one happened within _JWKS_MIN_REFRESH_INTERVAL.
    """
    global _jwks_last_refresh
    if not oidc_enabled():
        return
    now = time.monotonic()
    if not force and now - _jwks_last_refresh < _JWKS_MIN_REFRESH_INTERVAL:
        return
    _jwks_last_refresh = now
    try:
        discovery_url = f"{settings.authentik_issuer.rstrip('/')}/.well-known/openid-configuration"
        async with httpx.AsyncClient(timeout=10) as client:
            discovery = (await client.get(discovery_url)).raise_for_status().json()
            keys = (await client.get(discovery["jwks_uri"])).raise_for_status().json()
        loaded = {}
        for key in keys["keys"]:
            try:
                loaded[key["kid"]] = jwt.PyJWK.from_dict(key).key
            except Exception as exc:  # unsupported kty etc. — skip, don't fail the whole set
                logger.warning("Skipping JWKS key %s: %s", key.get("kid"), exc)
        _jwks.clear()
        _jwks.update(loaded)
        logger.info("Loaded %d JWKS keys from Authentik", len(_jwks))
    except Exception as exc:
        logger.error("Failed to fetch JWKS from Authentik: %s", exc)


async def _validate_oidc_jwt(token: str, header: dict) -> str:
    if not _jwks:
        await refresh_jwks(force=False)

    kid = header.get("kid")
    key = _jwks.get(kid)

    if key is None:
        # Might be a new key after rotation — refresh (throttled) and retry once
        await refresh_jwks(force=False)
        key = _jwks.get(kid)

    if key is None:
        raise HTTPException(status_code=401, detail="Unknown JWT signing key")

    decode_kwargs: dict = {
        "algorithms": _OIDC_ALGORITHMS,
        "issuer": settings.authentik_issuer,
    }
    if settings.authentik_client_id:
        decode_kwargs["audience"] = settings.authentik_client_id
    else:
        decode_kwargs["options"] = {"verify_aud": False}

    try:
        payload = jwt.decode(token, key, **decode_kwargs)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidIssuerError:
        raise HTTPException(status_code=401, detail="Token issuer mismatch")
    except jwt.InvalidAudienceError:
        raise HTTPException(status_code=401, detail="Token audience mismatch")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")

    return payload.get("preferred_username") or payload.get("email") or payload.get("sub") or "unknown"


def _validate_dev_jwt(token: str) -> str:
    try:
        payload = jwt.decode(
            token,
            settings.dev_password,
            algorithms=[_DEV_ALGORITHM],
            issuer="kio-dev",
        )
        return payload.get("sub", "dev")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")


async def _validate_jwt(token: str) -> str:
    """Route a bearer JWT to the right validator based on its signing algorithm.

    Authentik signs with an asymmetric key (RS*/ES*); dev tokens minted by
    POST /auth/login are HS256. Both may be enabled at once, so the dev login
    keeps working as a break-glass path while Authentik is the primary mechanism.
    """
    try:
        header = jwt.get_unverified_header(token)
    except jwt.DecodeError as exc:
        raise HTTPException(status_code=401, detail=f"Malformed token: {exc}")

    alg = header.get("alg")
    if alg == _DEV_ALGORITHM and dev_login_enabled():
        return _validate_dev_jwt(token)
    if alg in _OIDC_ALGORITHMS and oidc_enabled():
        return await _validate_oidc_jwt(token, header)
    raise HTTPException(status_code=401, detail="Token type not accepted")


async def _check_db_api_key(raw: str, session: AsyncSession) -> bool:
    """Return True if raw matches an active DB-managed API key, updating last_used_at."""
    from app.models.api_key import ApiKey

    token_hash = ApiKey.hash(raw)
    result = await session.execute(
        select(ApiKey).where(ApiKey.token_hash == token_hash, ApiKey.is_active == True)  # noqa: E712
    )
    key = result.scalar_one_or_none()
    if key is None:
        return False
    await session.execute(update(ApiKey).where(ApiKey.id == key.id).values(last_used_at=func.now()))
    await session.commit()
    return True


async def require_dashboard_auth(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
    api_key: str | None = Security(_api_key_header),
    token: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> str:
    if settings.auth_disabled:
        return "dev"

    # Check X-API-Key header against static config keys (fast path), then DB keys
    if api_key:
        if api_key in settings.api_keys_set:
            return "apikey"
        if await _check_db_api_key(api_key, session):
            return "apikey"

    # Resolve the raw token from Bearer header or ?token= query param (needed for EventSource)
    raw_token = None
    if credentials:
        raw_token = credentials.credentials
    elif token:
        raw_token = token

    if raw_token:
        if raw_token in settings.api_keys_set:
            return "apikey"
        if await _check_db_api_key(raw_token, session):
            return "apikey"
        if oidc_enabled() or dev_login_enabled():
            return await _validate_jwt(raw_token)

    raise HTTPException(
        status_code=401,
        detail="Unauthorized",
        headers={"WWW-Authenticate": "Bearer"},
    )
