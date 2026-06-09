import logging
from datetime import datetime, timezone

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

# kid -> public key object, populated at startup and refreshed on unknown kid
_jwks: dict = {}


async def refresh_jwks() -> None:
    if not settings.authentik_issuer:
        return
    try:
        discovery_url = f"{settings.authentik_issuer.rstrip('/')}/.well-known/openid-configuration"
        async with httpx.AsyncClient(timeout=10) as client:
            discovery = (await client.get(discovery_url)).raise_for_status().json()
            keys = (await client.get(discovery["jwks_uri"])).raise_for_status().json()
        _jwks.clear()
        for key in keys["keys"]:
            _jwks[key["kid"]] = jwt.algorithms.RSAAlgorithm.from_jwk(key)
        logger.info("Loaded %d JWKS keys from Authentik", len(_jwks))
    except Exception as exc:
        logger.error("Failed to fetch JWKS from Authentik: %s", exc)


async def _validate_jwt(token: str) -> str:
    if not _jwks:
        await refresh_jwks()

    try:
        header = jwt.get_unverified_header(token)
    except jwt.DecodeError as exc:
        raise HTTPException(status_code=401, detail=f"Malformed token: {exc}")

    kid = header.get("kid")
    key = _jwks.get(kid)

    if key is None:
        # Might be a new key after rotation — refresh once
        await refresh_jwks()
        key = _jwks.get(kid)

    if key is None:
        raise HTTPException(status_code=401, detail="Unknown JWT signing key")

    try:
        payload = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            options={"verify_aud": False},
            issuer=settings.authentik_issuer or None,
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidIssuerError:
        raise HTTPException(status_code=401, detail="Token issuer mismatch")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")

    return payload.get("preferred_username") or payload.get("sub") or "unknown"


def _validate_dev_jwt(token: str) -> str:
    try:
        payload = jwt.decode(
            token,
            settings.dev_password,
            algorithms=["HS256"],
            issuer="kio-dev",
        )
        return payload.get("sub", "dev")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")


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
    await session.execute(
        update(ApiKey).where(ApiKey.id == key.id).values(last_used_at=func.now())
    )
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
        if settings.authentik_issuer:
            return await _validate_jwt(raw_token)
        if settings.dev_password:
            return _validate_dev_jwt(raw_token)

    raise HTTPException(
        status_code=401,
        detail="Unauthorized",
        headers={"WWW-Authenticate": "Bearer"},
    )
