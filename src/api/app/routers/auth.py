import time

import jwt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])

_ALG = "HS256"
_ISS = "kio-dev"
_TTL = 8 * 3600


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(body: LoginRequest):
    if not settings.dev_username or not settings.dev_password:
        raise HTTPException(status_code=404, detail="Dev auth not configured")
    if body.username != settings.dev_username or body.password != settings.dev_password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = jwt.encode(
        {"sub": body.username, "exp": int(time.time()) + _TTL, "iss": _ISS},
        settings.dev_password,
        algorithm=_ALG,
    )
    return {"access_token": token, "token_type": "bearer"}
