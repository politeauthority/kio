import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.api_key import ApiKey, generate_key

router = APIRouter(prefix="/settings/api-keys", tags=["api-keys"])


class ApiKeyRead(BaseModel):
    id: uuid.UUID
    name: str
    key_prefix: str
    created_at: datetime
    last_used_at: datetime | None
    is_active: bool

    model_config = {"from_attributes": True}


class ApiKeyCreated(ApiKeyRead):
    key: str  # only returned on creation


class ApiKeyCreate(BaseModel):
    name: str


class ApiKeyUpdate(BaseModel):
    name: str | None = None
    is_active: bool | None = None


@router.get("", response_model=list[ApiKeyRead])
async def list_api_keys(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(ApiKey).order_by(ApiKey.created_at.desc()))
    return result.scalars().all()


@router.post("", response_model=ApiKeyCreated, status_code=201)
async def create_api_key(body: ApiKeyCreate, session: AsyncSession = Depends(get_session)):
    key = generate_key()
    obj = ApiKey(
        name=body.name,
        key_prefix=key[:12],
        token_hash=ApiKey.hash(key),
        created_at=datetime.now(timezone.utc),
    )
    session.add(obj)
    await session.commit()
    await session.refresh(obj)
    # Validate the persisted row against the base schema (which has no `key`),
    # then attach the plaintext key — it exists only here, never on the ORM row,
    # so validating ApiKeyCreated directly against `obj` would fail on `key`.
    return ApiKeyCreated(**ApiKeyRead.model_validate(obj).model_dump(), key=key)


@router.patch("/{key_id}", response_model=ApiKeyRead)
async def update_api_key(
    key_id: uuid.UUID, body: ApiKeyUpdate, session: AsyncSession = Depends(get_session)
):
    obj = await session.get(ApiKey, key_id)
    if not obj:
        raise HTTPException(status_code=404, detail="API key not found")
    if body.name is not None:
        obj.name = body.name
    if body.is_active is not None:
        obj.is_active = body.is_active
    await session.commit()
    await session.refresh(obj)
    return obj


@router.delete("/{key_id}", status_code=204)
async def delete_api_key(key_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    obj = await session.get(ApiKey, key_id)
    if not obj:
        raise HTTPException(status_code=404, detail="API key not found")
    await session.delete(obj)
    await session.commit()
