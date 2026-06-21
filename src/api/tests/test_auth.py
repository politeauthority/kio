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
