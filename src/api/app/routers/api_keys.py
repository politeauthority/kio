import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.api_key import ApiKey
from app.schemas.api_key import ApiKeyCreate, ApiKeyCreated, ApiKeyRead

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


@router.get("", response_model=list[ApiKeyRead])
async def list_api_keys(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(ApiKey).order_by(ApiKey.created_at.desc()))
    return result.scalars().all()


@router.post("", response_model=ApiKeyCreated, status_code=201)
async def create_api_key(data: ApiKeyCreate, session: AsyncSession = Depends(get_session)):
    raw = f"kio_{secrets.token_urlsafe(32)}"
    key = ApiKey(
        id=uuid.uuid4(),
        token_hash=ApiKey.hash(raw),
        name=data.name,
    )
    session.add(key)
    await session.commit()
    await session.refresh(key)
    return ApiKeyCreated(id=key.id, token=raw, name=key.name, created_at=key.created_at)


@router.delete("/{key_id}", status_code=204)
async def revoke_api_key(key_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(delete(ApiKey).where(ApiKey.id == key_id))
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="API key not found")
    await session.commit()
