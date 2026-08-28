"""Unit tests for app.auth — no HTTP layer, functions called directly."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.auth import _validate_dev_jwt, require_dashboard_auth

_SECRET = "super-secret-dev-password"


def _make_token(sub="testuser", exp_offset=3600, secret=_SECRET, iss="kio-dev") -> str:
    return jwt.encode(
        {"sub": sub, "iss": iss, "exp": int(time.time()) + exp_offset},
        secret,
        algorithm="HS256",
    )


def _empty_session():
    """Mock AsyncSession where no DB-managed API key matches.

    require_dashboard_auth gained a `session: AsyncSession = Depends(get_session)`
    param for DB-backed API keys. When called directly (no FastAPI DI), tests must
    supply a session; this one makes _check_db_api_key fall through (no row found).
    """
    session = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# _validate_dev_jwt
# ---------------------------------------------------------------------------


def test_dev_jwt_valid_returns_sub():
    token = _make_token()
    with patch("app.auth.settings") as s:
        s.dev_password = _SECRET
        result = _validate_dev_jwt(token)
    assert result == "testuser"


def test_dev_jwt_defaults_sub_to_dev():
    token = jwt.encode({"iss": "kio-dev", "exp": int(time.time()) + 3600}, _SECRET, algorithm="HS256")
    with patch("app.auth.settings") as s:
        s.dev_password = _SECRET
        result = _validate_dev_jwt(token)
    assert result == "dev"


def test_dev_jwt_expired_raises_401():
    token = _make_token(exp_offset=-100)
    with patch("app.auth.settings") as s:
        s.dev_password = _SECRET
        with pytest.raises(HTTPException) as exc:
            _validate_dev_jwt(token)
    assert exc.value.status_code == 401
    assert "expired" in exc.value.detail.lower()


def test_dev_jwt_wrong_secret_raises_401():
    token = _make_token(secret="wrong-secret")
    with patch("app.auth.settings") as s:
        s.dev_password = _SECRET
        with pytest.raises(HTTPException) as exc:
            _validate_dev_jwt(token)
    assert exc.value.status_code == 401


def test_dev_jwt_garbage_raises_401():
    with patch("app.auth.settings") as s:
        s.dev_password = _SECRET
        with pytest.raises(HTTPException) as exc:
            _validate_dev_jwt("not.a.valid.jwt")
    assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# require_dashboard_auth
# ---------------------------------------------------------------------------


async def test_auth_disabled_returns_dev():
    with patch("app.auth.settings") as s:
        s.auth_disabled = True
        s.api_keys_set = set()
        result = await require_dashboard_auth(credentials=None, api_key=None, token=None)
    assert result == "dev"


async def test_valid_api_key_header_returns_apikey():
    with patch("app.auth.settings") as s:
        s.auth_disabled = False
        s.api_keys_set = {"kio_valid123"}
        s.authentik_issuer = ""
        s.dev_password = ""
        result = await require_dashboard_auth(credentials=None, api_key="kio_valid123", token=None)
    assert result == "apikey"


async def test_invalid_api_key_falls_through_to_401():
    with patch("app.auth.settings") as s:
        s.auth_disabled = False
        s.api_keys_set = {"kio_valid123"}
        s.authentik_issuer = ""
        s.dev_password = ""
        with pytest.raises(HTTPException) as exc:
            await require_dashboard_auth(credentials=None, api_key="kio_wrong", token=None, session=_empty_session())
    assert exc.value.status_code == 401


async def test_no_credentials_raises_401():
    with patch("app.auth.settings") as s:
        s.auth_disabled = False
        s.api_keys_set = set()
        s.authentik_issuer = ""
        s.dev_password = ""
        with pytest.raises(HTTPException) as exc:
            await require_dashboard_auth(credentials=None, api_key=None, token=None)
    assert exc.value.status_code == 401


async def test_bearer_token_as_api_key():
    """A bearer token that matches a static API key is accepted."""
    creds = MagicMock(spec=HTTPAuthorizationCredentials)
    creds.credentials = "kio_statickey"
    with patch("app.auth.settings") as s:
        s.auth_disabled = False
        s.api_keys_set = {"kio_statickey"}
        s.authentik_issuer = ""
        s.dev_password = ""
        result = await require_dashboard_auth(credentials=creds, api_key=None, token=None)
    assert result == "apikey"


async def test_valid_dev_jwt_via_bearer():
    token = _make_token(sub="alice")
    creds = MagicMock(spec=HTTPAuthorizationCredentials)
    creds.credentials = token
    with patch("app.auth.settings") as s:
        s.auth_disabled = False
        s.api_keys_set = set()
        s.authentik_issuer = ""
        s.dev_password = _SECRET
        result = await require_dashboard_auth(credentials=creds, api_key=None, token=None, session=_empty_session())
    assert result == "alice"


async def test_expired_dev_jwt_via_bearer_raises_401():
    token = _make_token(exp_offset=-100)
    creds = MagicMock(spec=HTTPAuthorizationCredentials)
    creds.credentials = token
    with patch("app.auth.settings") as s:
        s.auth_disabled = False
        s.api_keys_set = set()
        s.authentik_issuer = ""
        s.dev_password = _SECRET
        with pytest.raises(HTTPException) as exc:
            await require_dashboard_auth(credentials=creds, api_key=None, token=None, session=_empty_session())
    assert exc.value.status_code == 401


async def test_token_query_param_accepted():
    """?token= query param (used by EventSource) should work like a Bearer token."""
    token = _make_token(sub="bob")
    with patch("app.auth.settings") as s:
        s.auth_disabled = False
        s.api_keys_set = set()
        s.authentik_issuer = ""
        s.dev_password = _SECRET
        result = await require_dashboard_auth(credentials=None, api_key=None, token=token, session=_empty_session())
    assert result == "bob"


# ---------------------------------------------------------------------------
# Authentik (OIDC) JWTs
# ---------------------------------------------------------------------------

from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

import app.auth as auth_mod  # noqa: E402

_ISSUER = "https://auth.example.com/application/o/kio/"
_CLIENT_ID = "kio-client-id"
_KID = "test-kid"
_RSA_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _make_oidc_token(
    sub="alice",
    username="alice",
    exp_offset=3600,
    iss=_ISSUER,
    aud=_CLIENT_ID,
    kid=_KID,
    key=_RSA_KEY,
) -> str:
    payload = {"sub": sub, "iss": iss, "exp": int(time.time()) + exp_offset}
    if username:
        payload["preferred_username"] = username
    if aud:
        payload["aud"] = aud
    return jwt.encode(payload, key, algorithm="RS256", headers={"kid": kid})


@pytest.fixture
def oidc_settings():
    """Settings with Authentik enabled, dev login enabled, and the test key loaded."""
    auth_mod._jwks.clear()
    auth_mod._jwks[_KID] = _RSA_KEY.public_key()
    with patch("app.auth.settings") as s, patch("app.auth.refresh_jwks", new=AsyncMock()) as refresh:
        s.auth_disabled = False
        s.api_keys_set = set()
        s.authentik_issuer = _ISSUER
        s.authentik_client_id = _CLIENT_ID
        s.dev_username = "dev"
        s.dev_password = _SECRET
        s.refresh_jwks = refresh
        yield s
    auth_mod._jwks.clear()


def _bearer(token):
    creds = MagicMock(spec=HTTPAuthorizationCredentials)
    creds.credentials = token
    return creds


async def test_oidc_jwt_valid_returns_preferred_username(oidc_settings):
    token = _make_oidc_token(sub="uuid-1", username="alice")
    result = await require_dashboard_auth(
        credentials=_bearer(token), api_key=None, token=None, session=_empty_session()
    )
    assert result == "alice"


async def test_oidc_jwt_falls_back_to_sub(oidc_settings):
    token = _make_oidc_token(sub="uuid-1", username=None)
    result = await require_dashboard_auth(
        credentials=_bearer(token), api_key=None, token=None, session=_empty_session()
    )
    assert result == "uuid-1"


async def test_oidc_jwt_wrong_audience_raises_401(oidc_settings):
    token = _make_oidc_token(aud="some-other-app")
    with pytest.raises(HTTPException) as exc:
        await require_dashboard_auth(credentials=_bearer(token), api_key=None, token=None, session=_empty_session())
    assert exc.value.status_code == 401
    assert "audience" in exc.value.detail.lower()


async def test_oidc_jwt_audience_not_checked_when_client_id_unset(oidc_settings):
    oidc_settings.authentik_client_id = ""
    token = _make_oidc_token(aud="some-other-app")
    result = await require_dashboard_auth(
        credentials=_bearer(token), api_key=None, token=None, session=_empty_session()
    )
    assert result == "alice"


async def test_oidc_jwt_wrong_issuer_raises_401(oidc_settings):
    token = _make_oidc_token(iss="https://evil.example.com/")
    with pytest.raises(HTTPException) as exc:
        await require_dashboard_auth(credentials=_bearer(token), api_key=None, token=None, session=_empty_session())
    assert exc.value.status_code == 401
    assert "issuer" in exc.value.detail.lower()


async def test_oidc_jwt_expired_raises_401(oidc_settings):
    token = _make_oidc_token(exp_offset=-100)
    with pytest.raises(HTTPException) as exc:
        await require_dashboard_auth(credentials=_bearer(token), api_key=None, token=None, session=_empty_session())
    assert exc.value.status_code == 401
    assert "expired" in exc.value.detail.lower()


async def test_oidc_jwt_unknown_kid_triggers_refresh_then_401(oidc_settings):
    token = _make_oidc_token(kid="rotated-kid")
    with pytest.raises(HTTPException) as exc:
        await require_dashboard_auth(credentials=_bearer(token), api_key=None, token=None, session=_empty_session())
    assert exc.value.status_code == 401
    assert "signing key" in exc.value.detail.lower()
    oidc_settings.refresh_jwks.assert_awaited()


async def test_oidc_jwt_signed_by_other_key_raises_401(oidc_settings):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = _make_oidc_token(key=other)  # same kid, different key
    with pytest.raises(HTTPException) as exc:
        await require_dashboard_auth(credentials=_bearer(token), api_key=None, token=None, session=_empty_session())
    assert exc.value.status_code == 401


async def test_dev_jwt_still_accepted_when_oidc_enabled(oidc_settings):
    """Dev login stays usable as a break-glass path alongside Authentik."""
    token = _make_token(sub="devuser")
    result = await require_dashboard_auth(
        credentials=_bearer(token), api_key=None, token=None, session=_empty_session()
    )
    assert result == "devuser"


async def test_dev_jwt_rejected_when_dev_login_unconfigured(oidc_settings):
    oidc_settings.dev_username = ""
    token = _make_token(sub="devuser")
    with pytest.raises(HTTPException) as exc:
        await require_dashboard_auth(credentials=_bearer(token), api_key=None, token=None, session=_empty_session())
    assert exc.value.status_code == 401


async def test_oidc_jwt_rejected_when_issuer_unconfigured(oidc_settings):
    oidc_settings.authentik_issuer = ""
    token = _make_oidc_token()
    with pytest.raises(HTTPException) as exc:
        await require_dashboard_auth(credentials=_bearer(token), api_key=None, token=None, session=_empty_session())
    assert exc.value.status_code == 401


async def test_hs256_token_cannot_impersonate_oidc(oidc_settings):
    """An HS256 token carrying Authentik's kid must never reach the OIDC validator (alg confusion)."""
    oidc_settings.dev_username = ""  # dev login off, so only the OIDC path could accept it
    token = jwt.encode(
        {"sub": "mallory", "iss": _ISSUER, "aud": _CLIENT_ID, "exp": int(time.time()) + 3600},
        "x" * 32,
        algorithm="HS256",
        headers={"kid": _KID},
    )
    with pytest.raises(HTTPException) as exc:
        await require_dashboard_auth(credentials=_bearer(token), api_key=None, token=None, session=_empty_session())
    assert exc.value.status_code == 401
    assert "not accepted" in exc.value.detail.lower()


async def test_refresh_jwks_is_throttled_when_not_forced():
    with (
        patch("app.auth.settings") as s,
        patch("app.auth.httpx.AsyncClient") as client_cls,
    ):
        s.authentik_issuer = _ISSUER
        auth_mod._jwks_last_refresh = time.monotonic()
        await auth_mod.refresh_jwks(force=False)
        client_cls.assert_not_called()
    auth_mod._jwks_last_refresh = 0.0


# ---------------------------------------------------------------------------
# GET /auth/config
# ---------------------------------------------------------------------------


async def test_auth_config_reports_oidc_and_dev_login(client):
    with patch("app.routers.auth.settings") as s, patch("app.auth.settings") as s2:
        for st in (s, s2):
            st.auth_disabled = False
            st.authentik_issuer = _ISSUER
            st.authentik_client_id = _CLIENT_ID
            st.authentik_display_name = "Colfax SSO"
            st.dev_username = "dev"
            st.dev_password = _SECRET
        resp = await client.get("/auth/config")
    assert resp.status_code == 200
    assert resp.json() == {
        "disabled": False,
        "oidc": {"authority": _ISSUER, "client_id": _CLIENT_ID, "display_name": "Colfax SSO"},
        "dev_login": True,
    }


async def test_auth_config_when_nothing_configured(client):
    with patch("app.routers.auth.settings") as s, patch("app.auth.settings") as s2:
        for st in (s, s2):
            st.auth_disabled = True
            st.authentik_issuer = ""
            st.dev_username = ""
            st.dev_password = ""
        resp = await client.get("/auth/config")
    assert resp.status_code == 200
    assert resp.json() == {"disabled": True, "oidc": None, "dev_login": False}
