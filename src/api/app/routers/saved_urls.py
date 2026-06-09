import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.saved_url import SavedUrl
from app.schemas.saved_url import SavedUrlCreate, SavedUrlRead, SavedUrlUpdate

router = APIRouter(prefix="/saved-urls", tags=["saved-urls"])


@router.get("", response_model=list[SavedUrlRead])
async def list_saved_urls(
    q: str | None = Query(default=None, description="Filter by name or URL"),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(SavedUrl).order_by(SavedUrl.name)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(SavedUrl.name.ilike(like), SavedUrl.url.ilike(like)))
    rows = await session.execute(stmt)
    return [SavedUrlRead.model_validate(r) for r in rows.scalars().all()]


@router.post("", response_model=SavedUrlRead, status_code=201)
async def create_saved_url(data: SavedUrlCreate, session: AsyncSession = Depends(get_session)):
    saved = SavedUrl(name=data.name, url=data.url, description=data.description)
    session.add(saved)
    await session.commit()
    await session.refresh(saved)
    return SavedUrlRead.model_validate(saved)


@router.get("/{url_id}", response_model=SavedUrlRead)
async def get_saved_url(url_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    row = await session.get(SavedUrl, url_id)
    if row is None:
        raise HTTPException(status_code=404, detail="URL not found")
    return SavedUrlRead.model_validate(row)


@router.put("/{url_id}", response_model=SavedUrlRead)
async def update_saved_url(
    url_id: uuid.UUID,
    data: SavedUrlUpdate,
    session: AsyncSession = Depends(get_session),
):
    row = await session.get(SavedUrl, url_id)
    if row is None:
        raise HTTPException(status_code=404, detail="URL not found")
    row.name = data.name
    row.url = data.url
    row.description = data.description
    await session.commit()
    await session.refresh(row)
    return SavedUrlRead.model_validate(row)


@router.delete("/{url_id}", status_code=204)
async def delete_saved_url(url_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    row = await session.get(SavedUrl, url_id)
    if row is None:
        raise HTTPException(status_code=404, detail="URL not found")
    await session.delete(row)
    await session.commit()
