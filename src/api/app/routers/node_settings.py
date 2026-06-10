"""Global node defaults — hosts, browser flags, and the default page stored in app_settings as JSON."""

from fastapi import APIRouter, Depends, HTTPException
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
_DEFAULT_URL_KEY = "global_default_url"


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


class DefaultUrlPayload(BaseModel):
    url: str


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


@router.get("/default-url")
async def get_global_default_url(session: AsyncSession = Depends(get_session)) -> dict:
    url = await _get_json_setting(session, _DEFAULT_URL_KEY, "")
    return {"url": url}


@router.put("/default-url")
async def set_global_default_url(
    body: DefaultUrlPayload, session: AsyncSession = Depends(get_session)
) -> dict:
    # The page a node shows when it has nothing else to do (boot with no playlist,
    # last tab closed). Empty clears it, so nodes fall back to their own start_url.
    url = body.url.strip()
    if url and not url.startswith(("http://", "https://", "about:")):
        raise HTTPException(status_code=422, detail="URL must start with http://, https://, or about:")
    await _set_json_setting(session, _DEFAULT_URL_KEY, url)
    # Push sync_settings so online nodes update their in-memory default immediately;
    # it becomes visible the next time a node is idle. Offline nodes pick it up on
    # their next settings checkin/boot.
    kiosks = await session.execute(select(Kiosk).where(Kiosk.status == "online"))
    for kiosk in kiosks.scalars().all():
        try:
            publish_command(str(kiosk.id), {"command": "sync_settings"})
        except Exception:
            pass  # MQTT unavailable — agent applies on next checkin
    return {"url": url}
