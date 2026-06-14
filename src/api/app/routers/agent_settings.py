import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.kiosk import Kiosk
from app.mqtt import publish_command
from app.services import settings_service

logger = logging.getLogger("kio.settings")

router = APIRouter(prefix="/settings/agent", tags=["settings"])


async def _notify_all_nodes(session: AsyncSession) -> None:
    """Tell every node to pull the new settings and apply them live.

    Best-effort per node: if MQTT is down the node still picks up the change on
    its next scheduled settings checkin, so a publish failure is not fatal.
    """
    result = await session.execute(select(Kiosk.id))
    for (kiosk_id,) in result.all():
        try:
            publish_command(str(kiosk_id), {"command": "sync_settings"})
        except Exception as exc:
            logger.warning("Failed to notify node %s of settings change: %s", kiosk_id, exc)


class AgentSettingsUpdate(BaseModel):
    heartbeat_interval_seconds: int | None = None
    heartbeat_jitter_seconds: int | None = None
    metadata_interval_seconds: int | None = None
    settings_checkin_seconds: int | None = None
    node_offline_threshold_seconds: int | None = None
    event_log_purge_days: int | None = None
    brightness_enabled: int | None = None
    brightness_default: int | None = None


@router.get("")
async def get_agent_settings(session: AsyncSession = Depends(get_session)) -> dict:
    return await settings_service.get_global_settings(session)


@router.put("")
async def update_agent_settings(
    payload: AgentSettingsUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict:
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        return await settings_service.get_global_settings(session)
    before = await settings_service.get_global_settings(session)
    try:
        result = await settings_service.update_global_settings(session, updates)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Only bounce the fleet when a node-affecting setting actually changed.
    changed = {k for k in result if result[k] != before.get(k)}
    if changed & settings_service.NODE_AFFECTING_KEYS:
        await _notify_all_nodes(session)

    return result
