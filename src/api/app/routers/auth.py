import time

import jwt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.auth import dev_login_enabled, oidc_enabled
from app.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])

_ALG = "HS256"
_ISS = "kio-dev"
_TTL = 8 * 3600


class LoginRequest(BaseModel):
    username: str
    password: str


class OidcConfig(BaseModel):
    authority: str
    client_id: str
    display_name: str


class AuthConfig(BaseModel):
    # True when the server enforces no dashboard auth at all (local dev).
    disabled: bool
    # Present when Authentik login is configured. The UI drives the
    # Authorization Code + PKCE flow against `authority` with `client_id`.
    oidc: OidcConfig | None
    # True when POST /auth/login (static username/password) is available.
    dev_login: bool


@router.get("/config", response_model=AuthConfig)
async def auth_config() -> AuthConfig:
    """Public: tells the UI which login mechanisms this server supports.

    Nothing here is secret — the OIDC client is a public (PKCE) client and the
    authority URL is discoverable from the login redirect anyway.
    """
    oidc = None
    if oidc_enabled():
        oidc = OidcConfig(
            authority=settings.authentik_issuer,
            client_id=settings.authentik_client_id,
            display_name=settings.authentik_display_name,
        )
    return AuthConfig(disabled=settings.auth_disabled, oidc=oidc, dev_login=dev_login_enabled())


@router.post("/login")
async def login(body: LoginRequest):
    if not dev_login_enabled():
        raise HTTPException(status_code=404, detail="Dev auth not configured")
    if body.username != settings.dev_username or body.password != settings.dev_password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = jwt.encode(
        {"sub": body.username, "exp": int(time.time()) + _TTL, "iss": _ISS},
        settings.dev_password,
        algorithm=_ALG,
    )
    return {"access_token": token, "token_type": "bearer"}
