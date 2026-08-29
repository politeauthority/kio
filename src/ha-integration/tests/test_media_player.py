"""The playlist media player mirrors the kiosk's playlist_state and drives the
dedicated /playlist endpoints; selecting a source attaches then plays."""

from aioresponses import aioresponses
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kio.const import CONF_API_URL, DOMAIN
from custom_components.kio.media_player import playlist_options

from .common import make_kiosk

API = "http://kio.test"
KIOSK = "11111111-1111-1111-1111-111111111111"
LOBBY_PL = "aaaaaaaa-0000-0000-0000-000000000001"
DEMO_PL = "bbbbbbbb-0000-0000-0000-000000000002"

PLAYLISTS = [
    {"id": LOBBY_PL, "name": "Lobby loop", "item_count": 3},
    {"id": DEMO_PL, "name": "Demo", "item_count": 1},
]


def _entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_API_URL: API})
    entry.add_to_hass(hass)
    return entry


def _requests(m: aioresponses, method: str) -> list[tuple[str, dict | None]]:
    return [
        (str(key[1]), req.kwargs.get("json"))
        for key, calls in m.requests.items()
        if key[0] == method
        for req in calls
    ]


async def _setup(hass: HomeAssistant, m: aioresponses, kiosk: dict, repeat: bool = True) -> MockConfigEntry:
    entry = _entry(hass)
    # repeat=False when a test re-registers /kiosks later: aioresponses serves the
    # first still-live registration, so a repeating one would shadow the update.
    m.get(f"{API}/kiosks", payload=[kiosk], repeat=repeat)
    m.get(f"{API}/saved-urls", payload=[], repeat=True)
    m.get(f"{API}/playlists", payload=PLAYLISTS, repeat=True)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


# --- option mapping -----------------------------------------------------------


def test_playlist_options_map_name_to_id():
    assert playlist_options(PLAYLISTS) == {"Lobby loop": LOBBY_PL, "Demo": DEMO_PL}


def test_playlist_options_disambiguate_duplicate_names():
    rows = [{"id": LOBBY_PL, "name": "Loop"}, {"id": DEMO_PL, "name": "Loop"}]
    assert playlist_options(rows) == {"Loop": LOBBY_PL, "Loop (bbbbbbbb)": DEMO_PL}


# --- state -----------------------------------------------------------------------


async def test_idle_with_attached_playlist(hass: HomeAssistant) -> None:
    with aioresponses() as m:
        await _setup(hass, m, make_kiosk(playlist_id=LOBBY_PL, playlist_state=None))

    state = hass.states.get("media_player.lobby_playlist")
    assert state is not None
    assert state.state == "idle"
    assert state.attributes["source"] == "Lobby loop"
    assert state.attributes["source_list"] == ["Lobby loop", "Demo"]


async def test_playing_and_paused_follow_playlist_state(hass: HomeAssistant) -> None:
    with aioresponses() as m:
        entry = await _setup(
            hass,
            m,
            make_kiosk(playlist_id=LOBBY_PL, playlist_state={"idx": 1, "total": 3, "paused": False}),
            repeat=False,
        )
        state = hass.states.get("media_player.lobby_playlist")
        assert state.state == "playing"
        assert state.attributes["media_title"] == "Lobby loop"
        assert state.attributes["media_track"] == 2
        assert state.attributes["item_count"] == 3

        m.get(
            f"{API}/kiosks",
            payload=[make_kiosk(playlist_id=LOBBY_PL, playlist_state={"idx": 1, "total": 3, "paused": True})],
            repeat=True,
        )
        await hass.data[DOMAIN][entry.entry_id].async_refresh()
        await hass.async_block_till_done()

    state = hass.states.get("media_player.lobby_playlist")
    assert state.state == "paused"
    assert state.attributes["paused"] is True


async def test_offline_kiosk_is_off(hass: HomeAssistant) -> None:
    with aioresponses() as m:
        await _setup(hass, m, make_kiosk(status="offline", playlist_state={"idx": 0, "total": 1}))
    assert hass.states.get("media_player.lobby_playlist").state == "off"


# --- commands ------------------------------------------------------------------


async def test_pause_stop_and_resume_hit_dedicated_endpoints(hass: HomeAssistant) -> None:
    playing = make_kiosk(playlist_id=LOBBY_PL, playlist_state={"idx": 0, "total": 3, "paused": False})
    with aioresponses() as m:
        await _setup(hass, m, playing)
        for verb in ("pause", "stop", "resume", "play"):
            m.post(f"{API}/kiosks/{KIOSK}/playlist/{verb}", status=204, repeat=True)

        await hass.services.async_call(
            "media_player", "media_pause", {"entity_id": "media_player.lobby_playlist"}, blocking=True
        )
        await hass.services.async_call(
            "media_player", "media_stop", {"entity_id": "media_player.lobby_playlist"}, blocking=True
        )
        # Not paused (state says playing) → play starts the playlist afresh.
        await hass.services.async_call(
            "media_player", "media_play", {"entity_id": "media_player.lobby_playlist"}, blocking=True
        )
        await hass.async_block_till_done()
        posted = [url for url, _ in _requests(m, "POST")]

    assert f"{API}/kiosks/{KIOSK}/playlist/pause" in posted
    assert f"{API}/kiosks/{KIOSK}/playlist/stop" in posted
    assert f"{API}/kiosks/{KIOSK}/playlist/play" in posted
    assert f"{API}/kiosks/{KIOSK}/playlist/resume" not in posted


async def test_play_while_paused_resumes(hass: HomeAssistant) -> None:
    paused = make_kiosk(playlist_id=LOBBY_PL, playlist_state={"idx": 0, "total": 3, "paused": True})
    with aioresponses() as m:
        await _setup(hass, m, paused)
        m.post(f"{API}/kiosks/{KIOSK}/playlist/resume", status=204)
        await hass.services.async_call(
            "media_player", "media_play", {"entity_id": "media_player.lobby_playlist"}, blocking=True
        )
        await hass.async_block_till_done()
        posted = [url for url, _ in _requests(m, "POST")]

    assert posted == [f"{API}/kiosks/{KIOSK}/playlist/resume"]


async def test_next_and_previous_wrap_via_goto(hass: HomeAssistant) -> None:
    playing = make_kiosk(playlist_id=LOBBY_PL, playlist_state={"idx": 2, "total": 3, "paused": False})
    with aioresponses() as m:
        await _setup(hass, m, playing)
        m.post(f"{API}/kiosks/{KIOSK}/playlist/goto", status=204, repeat=True)
        await hass.services.async_call(
            "media_player", "media_next_track", {"entity_id": "media_player.lobby_playlist"}, blocking=True
        )
        await hass.services.async_call(
            "media_player", "media_previous_track", {"entity_id": "media_player.lobby_playlist"}, blocking=True
        )
        await hass.async_block_till_done()
        bodies = [body for url, body in _requests(m, "POST") if url.endswith("/goto")]

    assert bodies == [{"index": 0}, {"index": 1}]


async def test_select_source_attaches_then_plays(hass: HomeAssistant) -> None:
    with aioresponses() as m:
        await _setup(hass, m, make_kiosk(playlist_id=None, playlist_state=None))
        m.put(f"{API}/kiosks/{KIOSK}/playlist", status=204)
        m.post(f"{API}/kiosks/{KIOSK}/playlist/play", status=204)
        await hass.services.async_call(
            "media_player",
            "select_source",
            {"entity_id": "media_player.lobby_playlist", "source": "Demo"},
            blocking=True,
        )
        await hass.async_block_till_done()
        puts = _requests(m, "PUT")
        posts = [url for url, _ in _requests(m, "POST")]

    assert puts == [(f"{API}/kiosks/{KIOSK}/playlist", {"playlist_id": DEMO_PL})]
    assert posts == [f"{API}/kiosks/{KIOSK}/playlist/play"]


async def test_playlist_list_failure_keeps_previous_sources(hass: HomeAssistant) -> None:
    with aioresponses() as m:
        entry = await _setup(hass, m, make_kiosk(playlist_id=LOBBY_PL))
        assert hass.states.get("media_player.lobby_playlist").attributes["source_list"] == ["Lobby loop", "Demo"]

        m.get(f"{API}/playlists", status=500, repeat=True)
        await hass.data[DOMAIN][entry.entry_id].async_refresh()
        await hass.async_block_till_done()

    assert hass.states.get("media_player.lobby_playlist").attributes["source_list"] == ["Lobby loop", "Demo"]
