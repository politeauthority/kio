import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_session
from app.models.kiosk import Kiosk
from app.models.playlist import Playlist, PlaylistItem
from app.mqtt import publish_command
from app.schemas.playlist import (
    PlaylistCreate,
    PlaylistDetail,
    PlaylistReadWithCount,
    PlaylistUpdate,
)

router = APIRouter(prefix="/playlists", tags=["playlists"])


@router.get("", response_model=list[PlaylistReadWithCount])
async def list_playlists(session: AsyncSession = Depends(get_session)):
    count_sub = (
        select(PlaylistItem.playlist_id, func.count(PlaylistItem.id).label("item_count"))
        .group_by(PlaylistItem.playlist_id)
        .subquery()
    )
    stmt = (
        select(Playlist, func.coalesce(count_sub.c.item_count, 0).label("item_count"))
        .outerjoin(count_sub, count_sub.c.playlist_id == Playlist.id)
        .order_by(Playlist.created_at.desc())
    )
    rows = await session.execute(stmt)
    result = []
    for playlist, item_count in rows:
        d = PlaylistReadWithCount.model_validate(playlist)
        d.item_count = item_count
        result.append(d)
    return result


@router.post("", response_model=PlaylistDetail, status_code=201)
async def create_playlist(data: PlaylistCreate, session: AsyncSession = Depends(get_session)):
    playlist = Playlist(
        name=data.name,
        description=data.description,
        refresh_interval_seconds=data.refresh_interval_seconds,
    )
    session.add(playlist)
    await session.commit()
    stmt = select(Playlist).where(Playlist.id == playlist.id).options(selectinload(Playlist.items))
    playlist = (await session.execute(stmt)).scalar_one()
    return PlaylistDetail.model_validate(playlist)


@router.get("/{playlist_id}", response_model=PlaylistDetail)
async def get_playlist(playlist_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    stmt = select(Playlist).where(Playlist.id == playlist_id).options(selectinload(Playlist.items))
    playlist = (await session.execute(stmt)).scalar_one_or_none()
    if playlist is None:
        raise HTTPException(status_code=404, detail="Playlist not found")
    return PlaylistDetail.model_validate(playlist)


@router.put("/{playlist_id}", response_model=PlaylistDetail)
async def update_playlist(
    playlist_id: uuid.UUID,
    data: PlaylistUpdate,
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Playlist).where(Playlist.id == playlist_id).options(selectinload(Playlist.items))
    playlist = (await session.execute(stmt)).scalar_one_or_none()
    if playlist is None:
        raise HTTPException(status_code=404, detail="Playlist not found")

    playlist.name = data.name
    playlist.description = data.description
    playlist.refresh_interval_seconds = data.refresh_interval_seconds

    # Replace items wholesale
    for item in playlist.items:
        await session.delete(item)
    await session.flush()

    for i, item_in in enumerate(data.items):
        session.add(
            PlaylistItem(
                playlist_id=playlist.id,
                title=item_in.title,
                url=item_in.url,
                duration_seconds=item_in.duration_seconds,
                position=item_in.position if item_in.position else i,
            )
        )

    await session.commit()

    stmt = select(Playlist).where(Playlist.id == playlist_id).options(selectinload(Playlist.items))
    playlist = (await session.execute(stmt)).scalar_one()

    # Notify any kiosk that has this playlist attached so it can reload mid-play
    affected = (await session.execute(select(Kiosk).where(Kiosk.playlist_id == playlist_id))).scalars().all()
    if affected:
        items = [{"url": it.url, "duration_seconds": it.duration_seconds} for it in playlist.items]
        for kiosk in affected:
            try:
                publish_command(
                    str(kiosk.id),
                    {
                        "command": "sync_playlist",
                        "playlist_id": str(playlist_id),
                        "playlist_name": playlist.name,
                        "refresh_seconds": playlist.refresh_interval_seconds,
                        "items": items,
                    },
                )
            except Exception:
                pass  # MQTT unavailable — agent picks up changes on next play

    return PlaylistDetail.model_validate(playlist)


@router.delete("/{playlist_id}", status_code=204)
async def delete_playlist(playlist_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    stmt = select(Playlist).where(Playlist.id == playlist_id)
    playlist = (await session.execute(stmt)).scalar_one_or_none()
    if playlist is None:
        raise HTTPException(status_code=404, detail="Playlist not found")
    await session.delete(playlist)
    await session.commit()
