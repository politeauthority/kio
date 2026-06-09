import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_session
from app.models.command_log import CommandLog
from app.models.hardware_detect_log import HardwareDetectLog
from app.models.node_meta import NodeMeta
from app.models.playlist import Playlist
from app.mqtt import publish_command, publish_nav
from app.schemas.kiosk import KioskCreate, KioskRead, KioskUpdate
from app.services import kiosk_service

router = APIRouter(prefix="/kiosks", tags=["kiosks"])


def dispatch_command(session, kiosk_id, *, command: str, subject: str | None = None, payload: dict) -> uuid.UUID:
    """Publish an MQTT command tagged with a fresh CommandLog id and record the
    matching pending dashboard log entry. The agent echoes the id back when it acks,
    so results match by id rather than by re-formatting the command string on both
    sides (which silently broke whenever the two formats drifted).

    `command` is the bare event type (e.g. "navigate"); `subject` is what it acted
    on (e.g. the URL) and is stored separately so it doesn't pollute the type filter."""
    log_id = uuid.uuid4()
    publish_command(str(kiosk_id), {**payload, "command_id": str(log_id)})
    session.add(CommandLog(id=log_id, kiosk_id=kiosk_id, command=command, subject=subject, source="dashboard"))
    return log_id


@router.get("", response_model=list[KioskRead])
async def list_kiosks(session: AsyncSession = Depends(get_session)):
    return await kiosk_service.get_all(session)


@router.post("", response_model=KioskRead, status_code=201)
async def create_kiosk(data: KioskCreate, session: AsyncSession = Depends(get_session)):
    return await kiosk_service.create(session, data)


@router.get("/{kiosk_id}", response_model=KioskRead)
async def get_kiosk(kiosk_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    kiosk = await kiosk_service.get_by_id(session, kiosk_id)
    if kiosk is None:
        raise HTTPException(status_code=404, detail="Kiosk not found")
    return kiosk


@router.patch("/{kiosk_id}", response_model=KioskRead)
async def update_kiosk(
    kiosk_id: uuid.UUID,
    data: KioskUpdate,
    session: AsyncSession = Depends(get_session),
):
    kiosk = await kiosk_service.update_kiosk(session, kiosk_id, data)
    if kiosk is None:
        raise HTTPException(status_code=404, detail="Kiosk not found")
    return kiosk


@router.delete("/{kiosk_id}", status_code=204)
async def delete_kiosk(kiosk_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    deleted = await kiosk_service.delete(session, kiosk_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Kiosk not found")


# ---------------------------------------------------------------------------
# Node meta
# ---------------------------------------------------------------------------


class NodeMetaRead(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    key: str
    value: object
    updated_at: datetime


class NodeMetaWrite(BaseModel):
    key: str
    value: object


@router.get("/{kiosk_id}/meta", response_model=list[NodeMetaRead])
async def list_meta(kiosk_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    kiosk = await kiosk_service.get_by_id(session, kiosk_id)
    if kiosk is None:
        raise HTTPException(status_code=404, detail="Kiosk not found")
    return kiosk.meta_rows


@router.put("/{kiosk_id}/meta/{key}", response_model=NodeMetaRead, status_code=200)
async def set_meta(
    kiosk_id: uuid.UUID,
    key: str,
    payload: NodeMetaWrite,
    session: AsyncSession = Depends(get_session),
):

    kiosk = await kiosk_service.get_by_id(session, kiosk_id)
    if kiosk is None:
        raise HTTPException(status_code=404, detail="Kiosk not found")
    result = await session.execute(select(NodeMeta).where(NodeMeta.kiosk_id == kiosk_id, NodeMeta.key == key))
    row = result.scalar_one_or_none()
    if row:
        changed = row.value != payload.value
        row.value = payload.value
    else:
        changed = True
        row = NodeMeta(id=uuid.uuid4(), kiosk_id=kiosk_id, key=key, value=payload.value)
        session.add(row)
    await session.commit()
    await session.refresh(row)

    # Push a sync command so the node applies the change immediately. Only fire on
    # an actual value change so re-saving the edit page (which writes every meta
    # key) doesn't needlessly resync hosts or re-pull settings on the agent.
    META_SYNC_COMMANDS = {"extra_hosts": "sync_hosts", "settings_overrides": "sync_settings"}
    if changed and key in META_SYNC_COMMANDS:
        try:
            publish_command(str(kiosk_id), {"command": META_SYNC_COMMANDS[key]})
        except Exception:
            pass  # MQTT unavailable — agent will pick it up on next restart/checkin

    return row


@router.delete("/{kiosk_id}/meta/{key}", status_code=204)
async def delete_meta(
    kiosk_id: uuid.UUID,
    key: str,
    session: AsyncSession = Depends(get_session),
):
    from sqlalchemy import delete as sa_delete

    kiosk = await kiosk_service.get_by_id(session, kiosk_id)
    if kiosk is None:
        raise HTTPException(status_code=404, detail="Kiosk not found")
    await session.execute(sa_delete(NodeMeta).where(NodeMeta.kiosk_id == kiosk_id, NodeMeta.key == key))
    await session.commit()


ALLOWED_COMMANDS = {
    "reload",
    "reboot",
    "display_off",
    "display_on",
    "standby",
    "wake",
    "detect_capabilities",
    "sync_browser_flags",
    "sync_hosts",
}

ALLOWED_INPUTS = {"dp1", "dp2", "hdmi1", "hdmi2"}


class CommandPayload(BaseModel):
    command: str


@router.post("/{kiosk_id}/command", status_code=204)
async def send_command(
    kiosk_id: uuid.UUID,
    payload: CommandPayload,
    session: AsyncSession = Depends(get_session),
):
    if payload.command not in ALLOWED_COMMANDS:
        raise HTTPException(status_code=400, detail=f"Unknown command: {payload.command}")
    kiosk = await kiosk_service.get_by_id(session, kiosk_id)
    if kiosk is None:
        raise HTTPException(status_code=404, detail="Kiosk not found")
    dispatch_command(session, kiosk_id, command=payload.command, payload={"command": payload.command})
    await session.commit()


class NavPayload(BaseModel):
    url: str


@router.post("/{kiosk_id}/navigate", status_code=204)
async def navigate(
    kiosk_id: uuid.UUID,
    payload: NavPayload,
    session: AsyncSession = Depends(get_session),
):
    kiosk = await kiosk_service.get_by_id(session, kiosk_id)
    if kiosk is None:
        raise HTTPException(status_code=404, detail="Kiosk not found")
    log_id = uuid.uuid4()
    publish_nav(str(kiosk_id), payload.url, command_id=str(log_id))
    session.add(
        CommandLog(id=log_id, kiosk_id=kiosk_id, command="navigate", subject=payload.url, source="dashboard")
    )
    await session.commit()


class BrowserTabOpenPayload(BaseModel):
    url: str


class BrowserTabNavPayload(BaseModel):
    url: str


@router.get("/{kiosk_id}/browsers")
async def list_browser_tabs(
    kiosk_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    kiosk = await kiosk_service.get_by_id(session, kiosk_id)
    if kiosk is None:
        raise HTTPException(status_code=404, detail="Kiosk not found")
    return kiosk.browser_tabs


@router.post("/{kiosk_id}/browsers", status_code=204)
async def open_browser_tab(
    kiosk_id: uuid.UUID,
    payload: BrowserTabOpenPayload,
    session: AsyncSession = Depends(get_session),
):
    kiosk = await kiosk_service.get_by_id(session, kiosk_id)
    if kiosk is None:
        raise HTTPException(status_code=404, detail="Kiosk not found")
    dispatch_command(session, kiosk_id, command="open_tab", subject=payload.url,
                     payload={"command": "open_tab", "url": payload.url})
    await session.commit()


@router.delete("/{kiosk_id}/browsers/{tab_id}", status_code=204)
async def close_browser_tab(
    kiosk_id: uuid.UUID,
    tab_id: str,
    session: AsyncSession = Depends(get_session),
):
    kiosk = await kiosk_service.get_by_id(session, kiosk_id)
    if kiosk is None:
        raise HTTPException(status_code=404, detail="Kiosk not found")
    dispatch_command(session, kiosk_id, command="close_tab", subject=tab_id,
                     payload={"command": "close_tab", "tab_id": tab_id})
    await session.commit()


@router.post("/{kiosk_id}/browsers/{tab_id}/activate", status_code=204)
async def activate_browser_tab(
    kiosk_id: uuid.UUID,
    tab_id: str,
    session: AsyncSession = Depends(get_session),
):
    kiosk = await kiosk_service.get_by_id(session, kiosk_id)
    if kiosk is None:
        raise HTTPException(status_code=404, detail="Kiosk not found")
    dispatch_command(session, kiosk_id, command="activate_tab", subject=tab_id,
                     payload={"command": "activate_tab", "tab_id": tab_id})
    await session.commit()


@router.post("/{kiosk_id}/browsers/{tab_id}/refresh", status_code=204)
async def refresh_browser_tab(
    kiosk_id: uuid.UUID,
    tab_id: str,
    session: AsyncSession = Depends(get_session),
):
    kiosk = await kiosk_service.get_by_id(session, kiosk_id)
    if kiosk is None:
        raise HTTPException(status_code=404, detail="Kiosk not found")
    dispatch_command(session, kiosk_id, command="refresh_tab", subject=tab_id,
                     payload={"command": "refresh_tab", "tab_id": tab_id})
    await session.commit()


@router.post("/{kiosk_id}/browsers/{tab_id}/navigate", status_code=204)
async def navigate_browser_tab(
    kiosk_id: uuid.UUID,
    tab_id: str,
    payload: BrowserTabNavPayload,
    session: AsyncSession = Depends(get_session),
):
    kiosk = await kiosk_service.get_by_id(session, kiosk_id)
    if kiosk is None:
        raise HTTPException(status_code=404, detail="Kiosk not found")
    dispatch_command(session, kiosk_id, command="navigate_tab", subject=payload.url,
                     payload={"command": "navigate_tab", "tab_id": tab_id, "url": payload.url})
    await session.commit()


class BrowserFlagsPayload(BaseModel):
    flags: list[str]


@router.put("/{kiosk_id}/browser-flags", status_code=204)
async def set_browser_flags(
    kiosk_id: uuid.UUID,
    payload: BrowserFlagsPayload,
    session: AsyncSession = Depends(get_session),
):
    kiosk = await kiosk_service.get_by_id(session, kiosk_id)
    if kiosk is None:
        raise HTTPException(status_code=404, detail="Kiosk not found")
    kiosk.browser_flags = payload.flags
    await session.commit()
    publish_command(str(kiosk_id), {"command": "sync_browser_flags"})


class PlaylistAttachPayload(BaseModel):
    playlist_id: uuid.UUID


@router.put("/{kiosk_id}/playlist", status_code=204)
async def attach_playlist(
    kiosk_id: uuid.UUID,
    payload: PlaylistAttachPayload,
    session: AsyncSession = Depends(get_session),
):
    kiosk = await kiosk_service.get_by_id(session, kiosk_id)
    if kiosk is None:
        raise HTTPException(status_code=404, detail="Kiosk not found")
    playlist = await session.get(Playlist, payload.playlist_id)
    if playlist is None:
        raise HTTPException(status_code=404, detail="Playlist not found")
    kiosk.playlist_id = payload.playlist_id
    await session.commit()


@router.delete("/{kiosk_id}/playlist", status_code=204)
async def detach_playlist(
    kiosk_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    kiosk = await kiosk_service.get_by_id(session, kiosk_id)
    if kiosk is None:
        raise HTTPException(status_code=404, detail="Kiosk not found")
    kiosk.playlist_id = None
    await session.commit()


@router.post("/{kiosk_id}/playlist/play", status_code=204)
async def play_playlist(
    kiosk_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    kiosk = await kiosk_service.get_by_id(session, kiosk_id)
    if kiosk is None:
        raise HTTPException(status_code=404, detail="Kiosk not found")
    if kiosk.playlist_id is None:
        raise HTTPException(status_code=400, detail="No playlist attached to this kiosk")
    result = await session.execute(
        select(Playlist).where(Playlist.id == kiosk.playlist_id).options(selectinload(Playlist.items))
    )
    playlist = result.scalar_one_or_none()
    if playlist is None:
        raise HTTPException(status_code=404, detail="Attached playlist not found")
    if not playlist.items:
        raise HTTPException(status_code=400, detail="Playlist has no items")
    items = [{"url": it.url, "duration_seconds": it.duration_seconds} for it in playlist.items]
    dispatch_command(session, kiosk_id, command="play_playlist", subject=playlist.name, payload={
        "command": "play_playlist",
        "playlist_id": str(playlist.id),
        "playlist_name": playlist.name,
        "refresh_seconds": playlist.refresh_interval_seconds,
        "items": items,
    })
    await session.commit()


@router.post("/{kiosk_id}/playlist/stop", status_code=204)
async def stop_playlist(
    kiosk_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    kiosk = await kiosk_service.get_by_id(session, kiosk_id)
    if kiosk is None:
        raise HTTPException(status_code=404, detail="Kiosk not found")
    dispatch_command(session, kiosk_id, command="stop_playlist", payload={"command": "stop_playlist"})
    await session.commit()


class PlaylistGotoPayload(BaseModel):
    index: int = Field(..., ge=0)


@router.post("/{kiosk_id}/playlist/goto", status_code=204)
async def playlist_goto(
    kiosk_id: uuid.UUID,
    payload: PlaylistGotoPayload,
    session: AsyncSession = Depends(get_session),
):
    kiosk = await kiosk_service.get_by_id(session, kiosk_id)
    if kiosk is None:
        raise HTTPException(status_code=404, detail="Kiosk not found")

    # Build a rich subject: include playlist name, 1-based item number, and URL
    subject = f"item {payload.index + 1}"
    if kiosk.playlist_id:
        result = await session.execute(
            select(Playlist).where(Playlist.id == kiosk.playlist_id).options(selectinload(Playlist.items))
        )
        pl = result.scalar_one_or_none()
        if pl:
            subject = f"{pl.name} item {payload.index + 1}"
            if payload.index < len(pl.items):
                item = pl.items[payload.index]
                subject = f"{pl.name} [{payload.index + 1}] {item.url}"

    dispatch_command(session, kiosk_id, command="playlist_goto", subject=subject,
                     payload={"command": "playlist_goto", "index": payload.index})
    await session.commit()


class InputPayload(BaseModel):
    input: str


@router.post("/{kiosk_id}/input", status_code=204)
async def set_input(
    kiosk_id: uuid.UUID,
    payload: InputPayload,
    session: AsyncSession = Depends(get_session),
):
    if payload.input not in ALLOWED_INPUTS:
        raise HTTPException(status_code=400, detail=f"Unknown input: {payload.input}")
    kiosk = await kiosk_service.get_by_id(session, kiosk_id)
    if kiosk is None:
        raise HTTPException(status_code=404, detail="Kiosk not found")
    dispatch_command(session, kiosk_id, command="set_input", subject=payload.input,
                     payload={"command": "set_input", "input": payload.input})
    await session.commit()


class SetResolutionPayload(BaseModel):
    output: str
    mode: str
    rate: float | None = None


@router.post("/{kiosk_id}/set-resolution", status_code=204)
async def set_resolution(
    kiosk_id: uuid.UUID,
    payload: SetResolutionPayload,
    session: AsyncSession = Depends(get_session),
):
    kiosk = await kiosk_service.get_by_id(session, kiosk_id)
    if kiosk is None:
        raise HTTPException(status_code=404, detail="Kiosk not found")
    subject = f"{payload.output} {payload.mode}"
    if payload.rate is not None:
        subject += f" @ {payload.rate} Hz"
    dispatch_command(
        session, kiosk_id, command="set_resolution", subject=subject,
        payload={"command": "set_resolution", "output": payload.output,
                 "mode": payload.mode, "rate": payload.rate},
    )
    # Persist the chosen resolution so the agent re-applies it after reboot
    meta_value = {"output": payload.output, "mode": payload.mode, "rate": payload.rate}
    result = await session.execute(
        select(NodeMeta).where(NodeMeta.kiosk_id == kiosk_id, NodeMeta.key == "display_resolution")
    )
    row = result.scalar_one_or_none()
    if row:
        row.value = meta_value
    else:
        session.add(NodeMeta(id=uuid.uuid4(), kiosk_id=kiosk_id, key="display_resolution", value=meta_value))
    await session.commit()


# A command the agent hasn't acknowledged within this window is treated as
# "no response" rather than perpetually "pending" — e.g. the agent was offline,
# restarted mid-command, or never received it. Computed at read time so a late
# acknowledgement still resolves the record normally.
COMMAND_RESPONSE_TIMEOUT_SECONDS = 120


class CommandLogRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    command: str
    subject: str | None
    source: str
    sent_at: datetime
    agent_success: bool | None
    agent_message: str | None
    agent_at: datetime | None
    # Derived display status: "ok" | "failed" | "pending" | "no_response"
    status: str


def _command_status(row: CommandLog, now: datetime) -> str:
    if row.agent_success is True:
        return "ok"
    if row.agent_success is False:
        return "failed"
    sent = row.sent_at
    if sent.tzinfo is None:
        sent = sent.replace(tzinfo=timezone.utc)
    if (now - sent).total_seconds() > COMMAND_RESPONSE_TIMEOUT_SECONDS:
        return "no_response"
    return "pending"


@router.get("/{kiosk_id}/command-log", response_model=list[CommandLogRead])
async def get_command_log(
    kiosk_id: uuid.UUID,
    response: Response,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    search: str = Query(default=""),
    session: AsyncSession = Depends(get_session),
):
    kiosk = await kiosk_service.get_by_id(session, kiosk_id)
    if kiosk is None:
        raise HTTPException(status_code=404, detail="Kiosk not found")

    base = select(CommandLog).where(CommandLog.kiosk_id == kiosk_id)
    if search:
        base = base.where(CommandLog.command.ilike(f"%{search}%"))

    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (await session.execute(base.order_by(CommandLog.sent_at.desc()).limit(limit).offset(offset))).scalars().all()

    now = datetime.now(timezone.utc)
    result = [
        CommandLogRead(
            id=r.id,
            command=r.command,
            subject=r.subject,
            source=r.source,
            sent_at=r.sent_at,
            agent_success=r.agent_success,
            agent_message=r.agent_message,
            agent_at=r.agent_at,
            status=_command_status(r, now),
        )
        for r in rows
    ]

    response.headers["X-Total-Count"] = str(total)
    return result


@router.get("/{kiosk_id}/hardware-detect-log")
async def get_hardware_detect_log(
    kiosk_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    kiosk = await kiosk_service.get_by_id(session, kiosk_id)
    if kiosk is None:
        raise HTTPException(status_code=404, detail="Kiosk not found")
    result = await session.execute(
        select(HardwareDetectLog)
        .where(HardwareDetectLog.kiosk_id == kiosk_id)
        .order_by(HardwareDetectLog.detected_at.desc())
        .limit(1)
    )
    log = result.scalar_one_or_none()
    if log is None:
        return None
    return {
        "id": str(log.id),
        "kiosk_id": str(log.kiosk_id),
        "detected_at": log.detected_at.isoformat(),
        "capabilities": log.capabilities,
        "probes": log.probes,
        "hardware_info": log.hardware_info,
    }
