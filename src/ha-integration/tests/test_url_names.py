"""Pretty names for registered URLs: the Current URL sensor shows the saved
URL's name when the API resolved one, and the Page select navigates by name."""

from aioresponses import aioresponses
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kio.const import CONF_API_URL, DOMAIN
from custom_components.kio.select import page_options

from .common import make_kiosk

API = "http://kio.test"
KIOSK_ID = "11111111-1111-1111-1111-111111111111"
SAVED = [
    {"id": "aaaa", "name": "Grafana — Office", "url": "https://grafana.lan/d/office"},
    {"id": "bbbb", "name": "Weather", "url": "https://weather.example/board"},
]


def _entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_API_URL: API})
    entry.add_to_hass(hass)
    return entry


def _on_grafana(**overrides) -> dict:
    base = {
        "current_url": "https://grafana.lan/d/office/",
        "current_url_name": "Grafana — Office",
        "current_saved_url_id": "aaaa",
    }
    return make_kiosk(**{**base, **overrides})


# --- option mapping --------------------------------------------------------------


def test_page_options_by_name():
    assert page_options(SAVED) == {
        "Grafana — Office": "https://grafana.lan/d/office",
        "Weather": "https://weather.example/board",
    }


def test_page_options_disambiguates_duplicate_names():
    rows = [
        {"id": "1", "name": "Dashboard", "url": "https://a.lan/x"},
        {"id": "2", "name": "Dashboard", "url": "https://b.lan/y"},
    ]
    assert page_options(rows) == {"Dashboard": "https://a.lan/x", "Dashboard (b.lan)": "https://b.lan/y"}


# --- Current URL sensor -----------------------------------------------------------


async def test_url_sensor_shows_saved_name_with_url_attribute(hass: HomeAssistant) -> None:
    entry = _entry(hass)
    with aioresponses() as m:
        m.get(f"{API}/kiosks", payload=[_on_grafana()], repeat=True)
        m.get(f"{API}/saved-urls", payload=SAVED, repeat=True)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    state = hass.states.get("sensor.lobby_current_url")
    assert state.state == "Grafana — Office"
    assert state.attributes["url"] == "https://grafana.lan/d/office/"
    assert state.attributes["saved_url_id"] == "aaaa"


async def test_url_sensor_falls_back_to_raw_url(hass: HomeAssistant) -> None:
    entry = _entry(hass)
    with aioresponses() as m:
        m.get(f"{API}/kiosks", payload=[make_kiosk(current_url="https://news.example/")], repeat=True)
        m.get(f"{API}/saved-urls", payload=SAVED, repeat=True)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    state = hass.states.get("sensor.lobby_current_url")
    assert state.state == "https://news.example/"
    assert state.attributes["saved_url_name"] is None


# --- Page select ------------------------------------------------------------------


async def test_page_select_lists_saved_urls_and_reflects_current(hass: HomeAssistant) -> None:
    entry = _entry(hass)
    with aioresponses() as m:
        m.get(f"{API}/kiosks", payload=[_on_grafana()], repeat=True)
        m.get(f"{API}/saved-urls", payload=SAVED, repeat=True)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    state = hass.states.get("select.lobby_page")
    assert state is not None
    assert state.attributes["options"] == ["Grafana — Office", "Weather"]
    assert state.state == "Grafana — Office"


async def test_page_select_unknown_when_page_not_saved(hass: HomeAssistant) -> None:
    entry = _entry(hass)
    with aioresponses() as m:
        m.get(f"{API}/kiosks", payload=[make_kiosk(current_url="https://news.example/")], repeat=True)
        m.get(f"{API}/saved-urls", payload=SAVED, repeat=True)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert hass.states.get("select.lobby_page").state == "unknown"


async def test_selecting_a_page_navigates_to_its_url(hass: HomeAssistant) -> None:
    entry = _entry(hass)
    with aioresponses() as m:
        m.get(f"{API}/kiosks", payload=[_on_grafana()], repeat=True)
        m.get(f"{API}/saved-urls", payload=SAVED, repeat=True)
        m.post(f"{API}/kiosks/{KIOSK_ID}/navigate", status=204)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": "select.lobby_page", "option": "Weather"},
            blocking=True,
        )
        await hass.async_block_till_done()

        posts = [req.kwargs.get("json") for key, calls in m.requests.items() if key[0] == "POST" for req in calls]
    assert {"url": "https://weather.example/board"} in posts


async def test_saved_url_fetch_failure_does_not_break_the_poll(hass: HomeAssistant) -> None:
    entry = _entry(hass)
    with aioresponses() as m:
        m.get(f"{API}/kiosks", payload=[_on_grafana()], repeat=True)
        m.get(f"{API}/saved-urls", status=500, repeat=True)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert hass.states.get("sensor.lobby_status").state == "online"
    assert hass.states.get("sensor.lobby_current_url").state == "Grafana — Office"
    assert hass.states.get("select.lobby_page").attributes["options"] == []
