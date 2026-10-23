"""Server-side data retention: the purges the hourly sweeper runs.

Each function takes a session and a window in days, deletes, and returns the
row count — kept pure enough to unit-test with a mocked session. Settings come
from Settings → Data retention (settings_service AGENT_SETTING_DEFAULTS).
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.command_log import CommandLog
from app.models.hardware_detect_log import HardwareDetectLog


def _cutoff(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


async def purge_command_logs(session: AsyncSession, days: int) -> int:
    """Event-log entries (dashboard commands + agent acks) older than `days`."""
    result = await session.execute(delete(CommandLog).where(CommandLog.sent_at < _cutoff(days)))
    return result.rowcount or 0


async def purge_hardware_detect_logs(session: AsyncSession, days: int) -> int:
    """Hardware-detect logs older than `days` — except each kiosk's newest one,
    which the agent's boot-time feature restore reads (routers/agent
    _restorable_features)."""
    newest = (
        select(HardwareDetectLog.kiosk_id, func.max(HardwareDetectLog.detected_at).label("latest"))
        .group_by(HardwareDetectLog.kiosk_id)
        .subquery()
    )
    keep = select(HardwareDetectLog.id).join(
        newest,
        (HardwareDetectLog.kiosk_id == newest.c.kiosk_id) & (HardwareDetectLog.detected_at == newest.c.latest),
    )
    result = await session.execute(
        delete(HardwareDetectLog).where(
            HardwareDetectLog.detected_at < _cutoff(days),
            HardwareDetectLog.id.not_in(keep),
        )
    )
    return result.rowcount or 0


async def run_retention(session: AsyncSession, settings_: dict) -> dict[str, int]:
    """One hourly pass over every server-side retention rule."""
    removed = {
        "command_logs": await purge_command_logs(session, settings_["event_log_purge_days"]),
        "hardware_detect_logs": await purge_hardware_detect_logs(session, settings_["hardware_log_purge_days"]),
    }
    await session.commit()
    return removed
