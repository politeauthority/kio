"""Playlist control for a kiosk as a Home Assistant media player.

One entity per kiosk. Maps kio's playlist verbs onto the media_player model so
it works with HA's stock cards and services without any custom UI:

  state          PLAYING when a playlist is loaded and rotating, PAUSED when it
                 is held on an item, IDLE when nothing is playing (a playlist may
                 still be attached), OFF when the kiosk is offline.
  source_list    every playlist in kio, by name; `source` is the attached one.
  select_source  attach that playlist to the kiosk and start it.
  play           start the attached playlist, or continue it when paused.
  pause / stop   hold on the current item / stop and release the tabs.
  next / prev    jump to the neighbouring item (wraps).

Playback state comes from the kiosk's `playlist_state` (reported by the agent
on every heartbeat), so a change made on the kio dashboard shows up here on
the next poll and vice versa.
"""

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import KioCoordinator
from .entity import KioEntity, setup_kio_platform


def playlist_options(playlists: list[dict]) -> dict[str, str]:
    """Playlists as {name: id}. A name used twice gets a short id suffix so both
    stay selectable (the dashboard allows duplicate names)."""
    options: dict[str, str] = {}
    for row in playlists:
        name, pid = row["name"], row["id"]
        if name in options and options[name] != pid:
            name = f"{name} ({pid[:8]})"
        options[name] = pid
    return options


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    def factory(coordinator: KioCoordinator, kiosk_id: str, added: frozenset, first: bool) -> list:
        return [KioPlaylistPlayer(coordinator, kiosk_id)] if first else []

    setup_kio_platform(hass, entry, async_add_entities, factory)


class KioPlaylistPlayer(KioEntity, MediaPlayerEntity):
    _attr_name = "Playlist"
    _attr_icon = "mdi:playlist-play"
    _attr_media_content_type = MediaType.PLAYLIST
    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.STOP
        | MediaPlayerEntityFeature.NEXT_TRACK
        | MediaPlayerEntityFeature.PREVIOUS_TRACK
        | MediaPlayerEntityFeature.SELECT_SOURCE
    )

    def __init__(self, coordinator: KioCoordinator, kiosk_id: str) -> None:
        super().__init__(coordinator, kiosk_id)
        self._attr_unique_id = f"{kiosk_id}_playlist"

    # --- state -----------------------------------------------------------------

    @property
    def _playlist_state(self) -> dict | None:
        state = self._kiosk.get("playlist_state")
        return state if isinstance(state, dict) else None

    @property
    def state(self) -> MediaPlayerState:
        if self._kiosk.get("status") != "online":
            return MediaPlayerState.OFF
        ps = self._playlist_state
        if ps is None:
            return MediaPlayerState.IDLE
        return MediaPlayerState.PAUSED if ps.get("paused") else MediaPlayerState.PLAYING

    @property
    def source_list(self) -> list[str]:
        return list(playlist_options(self.coordinator.playlists))

    @property
    def source(self) -> str | None:
        pid = self._kiosk.get("playlist_id")
        if not pid:
            return None
        for name, candidate in playlist_options(self.coordinator.playlists).items():
            if candidate == pid:
                return name
        return None

    @property
    def media_title(self) -> str | None:
        # The playlist name while one is loaded; HA cards show this as the
        # "now playing" line.
        return self.source if self._playlist_state is not None else None

    @property
    def media_track(self) -> int | None:
        ps = self._playlist_state
        if ps is None or ps.get("idx") is None:
            return None
        return int(ps["idx"]) + 1

    @property
    def extra_state_attributes(self) -> dict:
        ps = self._playlist_state or {}
        return {
            "playlist_id": self._kiosk.get("playlist_id"),
            "item_index": ps.get("idx"),
            "item_count": ps.get("total"),
            "item_started_at": ps.get("started_at"),
            "paused": bool(ps.get("paused")) if ps else False,
        }

    # --- commands --------------------------------------------------------------

    async def async_media_play(self) -> None:
        if self.state == MediaPlayerState.PAUSED:
            await self.coordinator.playlist_resume(self._kiosk_id)
        else:
            await self.coordinator.playlist_play(self._kiosk_id)

    async def async_media_pause(self) -> None:
        await self.coordinator.playlist_pause(self._kiosk_id)

    async def async_media_stop(self) -> None:
        await self.coordinator.playlist_stop(self._kiosk_id)

    async def async_media_next_track(self) -> None:
        await self._step(+1)

    async def async_media_previous_track(self) -> None:
        await self._step(-1)

    async def _step(self, delta: int) -> None:
        ps = self._playlist_state
        if not ps or not ps.get("total"):
            raise ValueError("No playlist is playing on this kiosk")
        total = int(ps["total"])
        target = (int(ps.get("idx") or 0) + delta) % total
        await self.coordinator.playlist_goto(self._kiosk_id, target)

    async def async_select_source(self, source: str) -> None:
        pid = playlist_options(self.coordinator.playlists).get(source)
        if pid is None:
            raise ValueError(f"{source!r} is not a kio playlist")
        await self.coordinator.playlist_attach(self._kiosk_id, pid)
        await self.coordinator.playlist_play(self._kiosk_id)
