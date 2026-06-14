import uuid
from datetime import datetime, timedelta, timezone
from typing import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.command_log import CommandLog
from app.models.hardware_detect_log import HardwareDetectLog
from app.models.kiosk import Kiosk
from app.models.node_meta import NodeMeta
from app.schemas.kiosk import KioskCreate, KioskUpdate


async def get_all(session: AsyncSession) -> Sequence[Kiosk]:
    result = await session.execute(select(Kiosk).order_by(Kiosk.name))
    return result.scalars().all()


async def get_by_id(session: AsyncSession, kiosk_id: uuid.UUID) -> Kiosk | None:
    return await session.get(Kiosk, kiosk_id)


async def create(session: AsyncSession, data: KioskCreate) -> Kiosk:
    kiosk = Kiosk(id=uuid.uuid4(), name=data.name, hostname=data.hostname)
    session.add(kiosk)
    await session.commit()
    await session.refresh(kiosk)
    return kiosk


async def update_kiosk(session: AsyncSession, kiosk_id: uuid.UUID, data: KioskUpdate) -> Kiosk | None:
    kiosk = await get_by_id(session, kiosk_id)
    if kiosk is None:
        return None
    if data.name is not None:
        kiosk.name = data.name
    if data.hostname is not None:
        kiosk.hostname = data.hostname
    if data.features is not None:
        kiosk.features = data.features
        await _store_features_overrides(session, kiosk_id, data.features)
    await session.commit()
    await session.refresh(kiosk)
    return kiosk


async def _store_features_overrides(
    session: AsyncSession, kiosk_id: uuid.UUID, user_features: list[str]
) -> None:
    """Persist user capability overrides vs the last detect log so they survive future detections."""
    log_result = await session.execute(
        select(HardwareDetectLog)
        .where(HardwareDetectLog.kiosk_id == kiosk_id)
        .order_by(HardwareDetectLog.detected_at.desc())
        .limit(1)
    )
    log = log_result.scalar_one_or_none()
    # No detect log yet: treat detection as having found nothing, so every
    # user-selected capability becomes an explicit enable override. Without this,
    # capability choices made before a node's first hardware detection were never
    # recorded and got silently dropped by the next heartbeat's features merge.
    detected = set(log.capabilities or []) if log else set()
    user = set(user_features or [])
    overrides: dict = {}
    overrides.update({cap: True for cap in user - detected})
    overrides.update({cap: False for cap in detected - user})

    meta_result = await session.execute(
        select(NodeMeta).where(NodeMeta.kiosk_id == kiosk_id, NodeMeta.key == "features_overrides")
    )
    row = meta_result.scalar_one_or_none()
    if row:
        row.value = overrides
    else:
        session.add(NodeMeta(id=uuid.uuid4(), kiosk_id=kiosk_id, key="features_overrides", value=overrides))


async def delete(session: AsyncSession, kiosk_id: uuid.UUID) -> bool:
    kiosk = await get_by_id(session, kiosk_id)
    if kiosk is None:
        return False
    await session.delete(kiosk)
    await session.commit()
    return True


async def update_kiosk_from_heartbeat(kiosk_id: str, payload: dict) -> None:
    """Called from the MQTT thread (via asyncio bridge) on each heartbeat."""
    try:
        uid = uuid.UUID(kiosk_id)
    except ValueError:
        return

    from app.database import async_session_factory

    async with async_session_factory() as session:
        kiosk = await get_by_id(session, uid)
        if kiosk is None:
            return
        kiosk.status = "online" if payload.get("online") else "offline"
        kiosk.current_url = payload.get("current_url")
        kiosk.last_seen = datetime.now(timezone.utc)
        await session.commit()


# Extra slack added on top of a heartbeat interval before a node may be declared
# offline. Covers normal network/processing jitter so a single late heartbeat
# doesn't trip a transition.
OFFLINE_GRACE_SECONDS = 15


async def mark_offline_kiosks(
    session: AsyncSession,
    threshold: int | None = None,
    *,
    heartbeat_interval: int | None = None,
    heartbeat_jitter: int = 0,
) -> None:
    """Mark kiosks that haven't been seen within the threshold as offline and log the event.

    `threshold` (seconds) is the live value from app_settings; when omitted it
    falls back to the static config default so existing callers keep working.

    Hysteresis: a node is never declared offline until it has been silent for clearly
    longer than one heartbeat interval (interval + jitter + grace). Without this floor a
    threshold set near the heartbeat cadence (e.g. 30s threshold with a 30s heartbeat)
    makes a perfectly healthy node flap offline→online on ordinary jitter, producing
    contradictory "node offline" / "node online" events in the same second.
    """
    if threshold is None:
        threshold = settings.node_offline_threshold_seconds
    if heartbeat_interval is None:
        from app.services.settings_service import AGENT_SETTING_DEFAULTS
        heartbeat_interval = AGENT_SETTING_DEFAULTS["heartbeat_interval_seconds"]

    floor = heartbeat_interval + heartbeat_jitter + OFFLINE_GRACE_SECONDS
    effective = max(threshold, floor)
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=effective)

    # Find kiosks that are about to be marked offline so we can log events
    result = await session.execute(select(Kiosk).where(Kiosk.last_seen < cutoff).where(Kiosk.status == "online"))
    going_offline = result.scalars().all()

    if going_offline:
        await session.execute(
            update(Kiosk)
            .where(Kiosk.last_seen < cutoff)
            .where(Kiosk.status == "online")
            .values(status="offline", updated_at=func.now())
        )
        for kiosk in going_offline:
            session.add(
                CommandLog(
                    id=uuid.uuid4(),
                    kiosk_id=kiosk.id,
                    command="node offline",
                    source="system",
                    agent_success=False,
                    agent_message=f"No heartbeat for >{effective}s",
                    agent_at=datetime.now(timezone.utc),
                )
            )

    await session.commit()
