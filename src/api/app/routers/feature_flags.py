from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.feature_flag import FeatureFlag

router = APIRouter(prefix="/settings/feature-flags", tags=["settings"])

KNOWN_FLAGS: dict[str, bool] = {
    "browser_management": True,
    "playlists": True,
    "debug": True,
}


class FeatureFlagRead(BaseModel):
    key: str
    enabled: bool


class FeatureFlagUpdate(BaseModel):
    enabled: bool


@router.get("", response_model=list[FeatureFlagRead])
async def list_feature_flags(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(FeatureFlag))
    rows = {r.key: r.enabled for r in result.scalars().all()}
    return [
        FeatureFlagRead(key=key, enabled=rows.get(key, default))
        for key, default in KNOWN_FLAGS.items()
    ]


@router.put("/{key}", response_model=FeatureFlagRead)
async def update_feature_flag(
    key: str,
    payload: FeatureFlagUpdate,
    session: AsyncSession = Depends(get_session),
):
    if key not in KNOWN_FLAGS:
        raise HTTPException(status_code=404, detail="Unknown feature flag")
    row = await session.get(FeatureFlag, key)
    if row:
        row.enabled = payload.enabled
    else:
        row = FeatureFlag(key=key, enabled=payload.enabled)
        session.add(row)
    await session.commit()
    return FeatureFlagRead(key=key, enabled=row.enabled)
