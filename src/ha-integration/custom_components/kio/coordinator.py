import logging
import socket
from datetime import timedelta
from urllib.parse import urlparse

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_API_IP, CONF_API_KEY, CONF_API_URL, DOMAIN

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)
_TIMEOUT = aiohttp.ClientTimeout(total=10)


class _StaticResolver(aiohttp.abc.AbstractResolver):
    """Resolver that maps one hostname to a fixed IP, falls back to stdlib for others."""

    def __init__(self, hostname: str, ip: str) -> None:
        self._hostname = hostname
        self._ip = ip

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET) -> list:
        if host == self._hostname:
            return [{"hostname": host, "host": self._ip, "port": port, "family": family, "proto": 0, "flags": 0}]
        return await aiohttp.ThreadedResolver().resolve(host, port, family)

    async def close(self) -> None:
        pass


def _make_session(api_url: str = "", api_ip: str = "") -> aiohttp.ClientSession:
    if api_ip:
        hostname = urlparse(api_url).hostname or ""
        resolver = _StaticResolver(hostname, api_ip)
    else:
        # Use ThreadedResolver (Python stdlib getaddrinfo) to avoid c-ares
        # appending the .local.hass.io search domain before the bare hostname.
        resolver = aiohttp.ThreadedResolver()
    connector = aiohttp.TCPConnector(resolver=resolver)
    return aiohttp.ClientSession(connector=connector)


class KioCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.api_url = entry.data[CONF_API_URL].rstrip("/")
        self.api_key = entry.data.get(CONF_API_KEY, "")
        self.api_ip = entry.data.get(CONF_API_IP, "")
        # One session per coordinator, created lazily on the event loop and
        # reused across polls and commands (closed in async_unload_entry).
        self._session_obj: aiohttp.ClientSession | None = None
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=SCAN_INTERVAL)

    @property
    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["X-API-Key"] = self.api_key
        return h

    def _session(self) -> aiohttp.ClientSession:
        if self._session_obj is None or self._session_obj.closed:
            self._session_obj = _make_session(self.api_url, self.api_ip)
        return self._session_obj

    async def async_close(self) -> None:
        if self._session_obj and not self._session_obj.closed:
            await self._session_obj.close()
            self._session_obj = None

    async def _async_update_data(self) -> dict:
        try:
            async with self._session().get(
                f"{self.api_url}/kiosks", headers=self._headers, timeout=_TIMEOUT
            ) as resp:
                resp.raise_for_status()
                kiosks = await resp.json()
            return {k["id"]: k for k in kiosks}
        except aiohttp.ClientResponseError as err:
            raise UpdateFailed(f"kio API returned {err.status}") from err
        except Exception as err:
            raise UpdateFailed(f"Error communicating with kio API: {err}") from err

    async def _command(self, method: str, path: str, json: dict | None = None) -> None:
        """Send a write to the kio API, then pull fresh state immediately.

        path is relative to the API root, e.g. f"/kiosks/{id}/command".
        """
        async with self._session().request(
            method, f"{self.api_url}{path}", json=json, headers=self._headers, timeout=_TIMEOUT
        ) as resp:
            resp.raise_for_status()
        await self.async_request_refresh()

    async def send_command(self, kiosk_id: str, command: str) -> None:
        await self._command("POST", f"/kiosks/{kiosk_id}/command", {"command": command})

    async def navigate(self, kiosk_id: str, url: str) -> None:
        await self._command("POST", f"/kiosks/{kiosk_id}/navigate", {"url": url})

    async def set_input(self, kiosk_id: str, input_name: str) -> None:
        await self._command("POST", f"/kiosks/{kiosk_id}/input", {"input": input_name})

    async def set_brightness(self, kiosk_id: str, value: int) -> None:
        await self._command("PUT", f"/kiosks/{kiosk_id}/brightness", {"value": value})

    async def update_agent(self, kiosk_id: str) -> None:
        # Dedicated endpoint, not the generic /command — the server injects the
        # git ref to land the node on an API-compatible build.
        await self._command("POST", f"/kiosks/{kiosk_id}/agent/update")
