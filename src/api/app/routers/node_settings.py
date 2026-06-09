"""Global node defaults — hosts and browser flags stored in app_settings as JSON."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.app_setting import AppSetting
from app.models.kiosk import Kiosk
from app.mqtt import publish_command

router = APIRouter(prefix="/settings/node", tags=["settings"])

_HOSTS_KEY = "global_extra_hosts"
_FLAGS_KEY = "global_browser_flags"


async def _get_json_setting(session: AsyncSession, key: str, default) -> object:
    row = await session.get(AppSetting, key)
    return row.value if row and row.value is not None else default


async def _set_json_setting(session: AsyncSession, key: str, value) -> None:
    row = await session.get(AppSetting, key)
    if row:
        row.value = value
    else:
        session.add(AppSetting(key=key, value=value))
    await session.commit()


class HostsPayload(BaseModel):
    hosts: list[str]


class BrowserFlagsPayload(BaseModel):
    flags: list[str]


@router.get("/hosts")
async def get_global_hosts(session: AsyncSession = Depends(get_session)) -> dict:
    hosts = await _get_json_setting(session, _HOSTS_KEY, [])
    return {"hosts": hosts}


@router.put("/hosts")
async def set_global_hosts(body: HostsPayload, session: AsyncSession = Depends(get_session)) -> dict:
    await _set_json_setting(session, _HOSTS_KEY, body.hosts)
    # Global hosts apply to every node — push sync_hosts so online kiosks apply the
    # change immediately. Offline kiosks pick it up via _sync_hosts on next restart.
    kiosks = await session.execute(select(Kiosk).where(Kiosk.status == "online"))
    for kiosk in kiosks.scalars().all():
        try:
            publish_command(str(kiosk.id), {"command": "sync_hosts"})
        except Exception:
            pass  # MQTT unavailable — agent applies on next restart/checkin
    return {"hosts": body.hosts}


@router.get("/browser-flags")
async def get_global_browser_flags(session: AsyncSession = Depends(get_session)) -> dict:
    flags = await _get_json_setting(session, _FLAGS_KEY, [])
    return {"flags": flags}


@router.put("/browser-flags")
async def set_global_browser_flags(
    body: BrowserFlagsPayload, session: AsyncSession = Depends(get_session)
) -> dict:
    await _set_json_setting(session, _FLAGS_KEY, body.flags)
    return {"flags": body.flags}
