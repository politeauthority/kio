import logging
import os
import socket
import ssl
from datetime import timedelta
from urllib.parse import urlparse

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_API_IP, CONF_API_KEY, CONF_API_URL, CONF_CA_CERT, DOMAIN

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


def ca_cert_path(hass: HomeAssistant, ca_cert: str) -> str:
    """Absolute path of the configured CA file ("" when none). A relative path
    is taken from the HA config dir, so presets can say `certs/foo.crt`."""
    ca_cert = (ca_cert or "").strip()
    if not ca_cert or os.path.isabs(ca_cert):
        return ca_cert
    return hass.config.path(ca_cert)


def _ssl_context(ca_cert: str) -> ssl.SSLContext | None:
    """Trust store for the kio API: the system CAs plus the PEM at `ca_cert`.

    None means "just the system CAs". A missing file also yields None, with a
    warning, so an install pointed at a publicly-signed API keeps working
    without the file. This reads from disk — call it from an executor, never
    on the event loop.
    """
    if not ca_cert:
        return None
    if not os.path.isfile(ca_cert):
        _LOGGER.warning("kio CA certificate %s not found; using the system trust store only", ca_cert)
        return None
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(cafile=ca_cert)
    return ctx


def _make_session(
    api_url: str = "", api_ip: str = "", ssl_context: ssl.SSLContext | None = None
) -> aiohttp.ClientSession:
    if api_ip:
        hostname = urlparse(api_url).hostname or ""
        resolver = _StaticResolver(hostname, api_ip)
    else:
        # Use ThreadedResolver (Python stdlib getaddrinfo) to avoid c-ares
        # appending the .local.hass.io search domain before the bare hostname.
        resolver = aiohttp.ThreadedResolver()
    # Leave aiohttp's default (verify with the system CAs) alone unless we have
    # a context with the extra CA loaded.
    ssl_kw = {"ssl": ssl_context} if ssl_context is not None else {}
    connector = aiohttp.TCPConnector(resolver=resolver, **ssl_kw)
    return aiohttp.ClientSession(connector=connector)


class KioCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.api_url = entry.data[CONF_API_URL].rstrip("/")
        self.api_key = entry.data.get(CONF_API_KEY, "")
        self.api_ip = entry.data.get(CONF_API_IP, "")
        self.ca_cert = ca_cert_path(hass, entry.data.get(CONF_CA_CERT, ""))
        # Built once, off the loop, the first time we talk to the API; None
        # when no CA is configured (or its file is missing).
        self._ssl_context: ssl.SSLContext | None = None
        self._ssl_ready = not self.ca_cert
        # One session per coordinator, created lazily on the event loop and
        # reused across polls and commands (closed in async_unload_entry).
        self._session_obj: aiohttp.ClientSession | None = None
        # Saved URLs (Settings → URLs in kio), refreshed alongside the kiosks. Each
        # is {"id", "name", "url", ...}. Kept on the coordinator rather than in
        # `data` so the kiosk-keyed shape every entity reads stays as it is.
        self.saved_urls: list[dict] = []
        # Playlists (GET /playlists), refreshed the same way; each is
        # {"id", "name", "item_count", ...}. Source list for the media players.
        self.playlists: list[dict] = []
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=SCAN_INTERVAL)

    @property
    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["X-API-Key"] = self.api_key
        return h

    async def _ensure_ssl(self) -> None:
        if not self._ssl_ready:
            self._ssl_context = await self.hass.async_add_executor_job(_ssl_context, self.ca_cert)
            self._ssl_ready = True

    def _session(self) -> aiohttp.ClientSession:
        if self._session_obj is None or self._session_obj.closed:
            self._session_obj = _make_session(self.api_url, self.api_ip, self._ssl_context)
        return self._session_obj

    async def async_close(self) -> None:
        if self._session_obj and not self._session_obj.closed:
            await self._session_obj.close()
            self._session_obj = None

    async def _async_update_data(self) -> dict:
        await self._ensure_ssl()
        try:
            async with self._session().get(
                f"{self.api_url}/kiosks", headers=self._headers, timeout=_TIMEOUT
            ) as resp:
                resp.raise_for_status()
                kiosks = await resp.json()
            await self._refresh_saved_urls()
            await self._refresh_playlists()
            return {k["id"]: k for k in kiosks}
        except aiohttp.ClientResponseError as err:
            raise UpdateFailed(f"kio API returned {err.status}") from err
        except Exception as err:
            raise UpdateFailed(f"Error communicating with kio API: {err}") from err

    async def _refresh_saved_urls(self) -> None:
        """Best effort: a failure here keeps the last list and never fails the poll,
        since the kiosk entities don't depend on it."""
        try:
            async with self._session().get(
                f"{self.api_url}/saved-urls", headers=self._headers, timeout=_TIMEOUT
            ) as resp:
                resp.raise_for_status()
                rows = await resp.json()
            self.saved_urls = [r for r in rows if r.get("name") and r.get("url")]
        except Exception as err:  # noqa: BLE001 — logged, not raised
            _LOGGER.debug("Saved URL refresh failed, keeping previous list: %s", err)

    async def _refresh_playlists(self) -> None:
        """Best effort, like the saved URLs: a failure keeps the last list."""
        try:
            async with self._session().get(
                f"{self.api_url}/playlists", headers=self._headers, timeout=_TIMEOUT
            ) as resp:
                resp.raise_for_status()
                rows = await resp.json()
            self.playlists = [r for r in rows if r.get("id") and r.get("name")]
        except Exception as err:  # noqa: BLE001 — logged, not raised
            _LOGGER.debug("Playlist refresh failed, keeping previous list: %s", err)

    async def _command(self, method: str, path: str, json: dict | None = None) -> None:
        """Send a write to the kio API, then pull fresh state immediately.

        path is relative to the API root, e.g. f"/kiosks/{id}/command".
        """
        await self._ensure_ssl()
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

    # Playlist control (media_player). All are dedicated endpoints, not /command.
    async def playlist_play(self, kiosk_id: str) -> None:
        await self._command("POST", f"/kiosks/{kiosk_id}/playlist/play")

    async def playlist_pause(self, kiosk_id: str) -> None:
        await self._command("POST", f"/kiosks/{kiosk_id}/playlist/pause")

    async def playlist_resume(self, kiosk_id: str) -> None:
        await self._command("POST", f"/kiosks/{kiosk_id}/playlist/resume")

    async def playlist_stop(self, kiosk_id: str) -> None:
        await self._command("POST", f"/kiosks/{kiosk_id}/playlist/stop")

    async def playlist_goto(self, kiosk_id: str, index: int) -> None:
        await self._command("POST", f"/kiosks/{kiosk_id}/playlist/goto", {"index": index})

    async def playlist_attach(self, kiosk_id: str, playlist_id: str) -> None:
        await self._command("PUT", f"/kiosks/{kiosk_id}/playlist", {"playlist_id": playlist_id})

    async def update_agent(self, kiosk_id: str) -> None:
        # Dedicated endpoint, not the generic /command — the server injects the
        # git ref to land the node on an API-compatible build.
        await self._command("POST", f"/kiosks/{kiosk_id}/agent/update")
