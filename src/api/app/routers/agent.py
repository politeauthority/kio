import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_session
from app.deps import get_node_kiosk
from app.models.command_log import CommandLog
from app.models.hardware_detect_log import HardwareDetectLog
from app.models.kiosk import Kiosk
from app.models.node_meta import NodeMeta
from app.models.playlist import Playlist
from app.mqtt import notify_subscribers

router = APIRouter(prefix="/agent", tags=["agent"])


class HeartbeatPayload(BaseModel):
    online: bool = True
    agent_version: str | None = None
    boot_id: str | None = None
    current_url: str | None = None
    current_input: str | None = None
    display_on: bool | None = None
    browser_tabs: list[dict] | None = None
    playlist_state: dict | None = None
    # Sent only on the hourly metadata heartbeat
    features: list[str] | None = None
    device_type: str | None = None
    ip_address: str | None = None


@router.post("/heartbeat", status_code=204)
async def heartbeat(
    payload: HeartbeatPayload,
    kiosk: Kiosk = Depends(get_node_kiosk),
    session: AsyncSession = Depends(get_session),
):
    was_offline = kiosk.status != "online"
    is_new_boot = (
        payload.boot_id is not None
        and payload.boot_id != "unknown"
        and payload.boot_id != kiosk.last_boot_id
        and kiosk.last_boot_id is not None  # don't fire on very first registration
    )
    kiosk.status = "online" if payload.online else "offline"
    kiosk.current_url = payload.current_url
    kiosk.last_seen = datetime.now(timezone.utc)

    if payload.boot_id:
        kiosk.last_boot_id = payload.boot_id

    if payload.online and is_new_boot:
        session.add(
            CommandLog(
                id=uuid.uuid4(),
                kiosk_id=kiosk.id,
                command="node rebooted",
                source="system",
                agent_success=True,
                agent_at=datetime.now(timezone.utc),
            )
        )
    elif payload.online and was_offline and not is_new_boot:
        session.add(
            CommandLog(
                id=uuid.uuid4(),
                kiosk_id=kiosk.id,
                command="node online",
                source="system",
                agent_success=True,
                agent_at=datetime.now(timezone.utc),
            )
        )
    if payload.features is not None:
        # Apply user overrides (from the edit page) on top of newly detected features
        meta_result = await session.execute(
            select(NodeMeta).where(NodeMeta.kiosk_id == kiosk.id, NodeMeta.key == "features_overrides")
        )
        meta_row = meta_result.scalar_one_or_none()
        overrides: dict = meta_row.value if meta_row else {}
        merged = set(payload.features)
        for cap, enabled in overrides.items():
            if enabled:
                merged.add(cap)
            else:
                merged.discard(cap)
        kiosk.features = sorted(merged)
    if payload.device_type is not None:
        kiosk.device_type = payload.device_type
    if payload.ip_address is not None:
        kiosk.ip_address = payload.ip_address
    if payload.current_input is not None:
        kiosk.current_input = payload.current_input
    if payload.display_on is not None:
        kiosk.display_on = payload.display_on
    if payload.agent_version is not None:
        kiosk.agent_version = payload.agent_version
    if payload.browser_tabs is not None:
        kiosk.browser_tabs = payload.browser_tabs
    # Always update playlist_state (None clears it when playback stops)
    kiosk.playlist_state = payload.playlist_state

    await session.commit()

    notify_subscribers(
        str(kiosk.id),
        {
            "online": payload.online,
            "current_url": payload.current_url,
            "browser_tabs": kiosk.browser_tabs,
            "playlist_state": kiosk.playlist_state,
        },
    )


@router.get("/config")
async def get_config(
    kiosk: Kiosk = Depends(get_node_kiosk),
) -> dict:
    return {
        "kiosk_id": str(kiosk.id),
        "mqtt_topic_prefix": settings.mqtt_topic_prefix,
        "mqtt_host": settings.mqtt_node_host or settings.mqtt_host,
        "mqtt_port": settings.mqtt_node_port,
    }


@router.get("/browser-flags")
async def get_browser_flags(
    kiosk: Kiosk = Depends(get_node_kiosk),
) -> list[str]:
    return kiosk.browser_flags


@router.get("/settings")
async def get_agent_settings(
    kiosk: Kiosk = Depends(get_node_kiosk),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Effective settings for this node: global defaults merged with per-node overrides.

    The agent fetches this on boot and on a recurring checkin (settings_checkin_seconds)
    to tune its heartbeat cadence and jitter.
    """
    from app.services import settings_service

    globals_ = await settings_service.get_global_settings(session)
    overrides = kiosk.meta.get(settings_service.OVERRIDES_META_KEY)
    result = settings_service.effective_settings(globals_, overrides)
    display_resolution = kiosk.meta.get("display_resolution")
    if display_resolution:
        result["display_resolution"] = display_resolution
    return result


@router.get("/meta")
async def get_meta(
    kiosk: Kiosk = Depends(get_node_kiosk),
) -> dict:
    return kiosk.meta


class AgentMetaPayload(BaseModel):
    value: object


@router.put("/meta/{key}", status_code=204)
async def put_meta(
    key: str,
    payload: AgentMetaPayload,
    kiosk: Kiosk = Depends(get_node_kiosk),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(NodeMeta).where(NodeMeta.kiosk_id == kiosk.id, NodeMeta.key == key))
    row = result.scalar_one_or_none()
    if row:
        row.value = payload.value
    else:
        session.add(NodeMeta(id=uuid.uuid4(), kiosk_id=kiosk.id, key=key, value=payload.value))
    await session.commit()


class HardwareDetectLogPayload(BaseModel):
    capabilities: list[str]
    probes: dict
    hardware_info: dict


@router.post("/hardware-detect-log", status_code=204)
async def post_hardware_detect_log(
    payload: HardwareDetectLogPayload,
    kiosk: Kiosk = Depends(get_node_kiosk),
    session: AsyncSession = Depends(get_session),
):
    session.add(
        HardwareDetectLog(
            id=uuid.uuid4(),
            kiosk_id=kiosk.id,
            capabilities=payload.capabilities,
            probes=payload.probes,
            hardware_info=payload.hardware_info,
        )
    )
    await session.commit()


class FilePermissionErrorPayload(BaseModel):
    file: str
    process: str = "agent"


@router.post("/file-permission-error", status_code=204)
async def post_file_permission_error(
    payload: FilePermissionErrorPayload,
    kiosk: Kiosk = Depends(get_node_kiosk),
    session: AsyncSession = Depends(get_session),
):
    key = "file_permission_errors"
    result = await session.execute(select(NodeMeta).where(NodeMeta.kiosk_id == kiosk.id, NodeMeta.key == key))
    row = result.scalar_one_or_none()

    entry = {
        "file": payload.file,
        "process": payload.process,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    errors = list(row.value) if row and isinstance(row.value, list) else []
    errors.append(entry)
    errors = errors[-50:]  # keep last 50

    if row:
        row.value = errors
    else:
        session.add(NodeMeta(id=uuid.uuid4(), kiosk_id=kiosk.id, key=key, value=errors))
    await session.commit()


class CommandLogPayload(BaseModel):
    command: str
    success: bool
    message: str | None = None
    command_id: uuid.UUID | None = None


@router.post("/command-log", status_code=204)
async def log_command(
    payload: CommandLogPayload,
    kiosk: Kiosk = Depends(get_node_kiosk),
    session: AsyncSession = Depends(get_session),
):
    now = datetime.now(timezone.utc)
    window = now - timedelta(minutes=5)

    record = None
    # Preferred: match the exact dashboard record by id (the agent echoes the
    # command_id we tagged the MQTT command with). Robust to label formatting.
    if payload.command_id is not None:
        record = (await session.execute(
            select(CommandLog).where(
                CommandLog.id == payload.command_id,
                CommandLog.kiosk_id == kiosk.id,
            )
        )).scalar_one_or_none()

    # Fallback for agent-initiated acks (no id) or older agents: match the most
    # recent pending dashboard record with the same command string.
    if record is None:
        record = (await session.execute(
            select(CommandLog)
            .where(
                CommandLog.kiosk_id == kiosk.id,
                CommandLog.command == payload.command,
                CommandLog.agent_success.is_(None),
                CommandLog.sent_at >= window,
            )
            .order_by(CommandLog.sent_at.desc())
            .limit(1)
        )).scalar_one_or_none()

    if record:
        record.agent_success = payload.success
        record.agent_message = payload.message
        record.agent_at = now
    else:
        # Agent-initiated (no matching dashboard record)
        session.add(
            CommandLog(
                id=uuid.uuid4(),
                kiosk_id=kiosk.id,
                command=payload.command,
                source="agent",
                agent_success=payload.success,
                agent_message=payload.message,
                agent_at=now,
            )
        )

    await session.commit()


@router.get("/state")
async def get_state(
    kiosk: Kiosk = Depends(get_node_kiosk),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Return last active state for boot-time resume.

    Only returns a playlist if it was actively playing before the last reboot
    (indicated by a non-null playlist_state). The agent calls this once on
    startup, before the first heartbeat clears the stored state.
    """
    if not kiosk.playlist_id or kiosk.playlist_state is None:
        return {"playlist": None}

    result = await session.execute(
        select(Playlist)
        .where(Playlist.id == kiosk.playlist_id)
        .options(selectinload(Playlist.items))
    )
    playlist = result.scalar_one_or_none()
    if not playlist or not playlist.items:
        return {"playlist": None}

    return {
        "playlist": {
            "id": str(playlist.id),
            "name": playlist.name,
            "refresh_seconds": playlist.refresh_interval_seconds,
            "items": [
                {"url": it.url, "duration_seconds": it.duration_seconds}
                for it in playlist.items
            ],
            "last_idx": kiosk.playlist_state.get("idx", 0),
        }
    }
