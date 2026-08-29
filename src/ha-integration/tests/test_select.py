"""The display-input select must reflect the dashboard's Input Configuration:
names from meta.input_labels, hidden inputs from meta.hidden_inputs."""

from aioresponses import aioresponses
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kio.const import CONF_API_URL, DOMAIN
from custom_components.kio.select import input_options

from .common import make_kiosk

API = "http://kio.test"

OFFICE_META = {
    "input_labels": {"hdmi1": "Laptop", "hdmi2": "Kio"},
    "hidden_inputs": ["dp1", "dp2"],
}


def _entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_API_URL: API})
    entry.add_to_hass(hass)
    return entry


def _office(**overrides) -> dict:
    base = {"features": ["input_switch"], "current_input": "hdmi2", "meta": OFFICE_META}
    return make_kiosk(**{**base, **overrides})


# --- option mapping -----------------------------------------------------------


def test_input_options_use_labels_and_drop_hidden():
    assert input_options(_office()) == {"Laptop": "hdmi1", "Kio": "hdmi2"}


def test_input_options_defaults_without_meta():
    assert input_options(make_kiosk(meta={})) == {
        "HDMI 1": "hdmi1",
        "HDMI 2": "hdmi2",
        "DP 1": "dp1",
        "DP 2": "dp2",
    }


def test_input_options_keeps_the_current_input_even_when_hidden():
    kiosk = _office(current_input="dp1")
    assert input_options(kiosk) == {"Laptop": "hdmi1", "Kio": "hdmi2", "DP 1": "dp1"}


def test_input_options_blank_label_falls_back_to_default():
    kiosk = make_kiosk(meta={"input_labels": {"hdmi1": "   "}})
    assert input_options(kiosk)["HDMI 1"] == "hdmi1"


def test_input_options_disambiguates_duplicate_labels():
    kiosk = make_kiosk(meta={"input_labels": {"hdmi1": "TV", "hdmi2": "TV"}, "hidden_inputs": ["dp1", "dp2"]})
    assert input_options(kiosk) == {"TV": "hdmi1", "TV (hdmi2)": "hdmi2"}


# --- entity behaviour ----------------------------------------------------------


async def test_select_exposes_labels_and_current_label(hass: HomeAssistant) -> None:
    entry = _entry(hass)
    with aioresponses() as m:
        m.get(f"{API}/kiosks", payload=[_office()], repeat=True)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    state = hass.states.get("select.lobby_display_input")
    assert state is not None
    assert state.state == "Kio"
    assert state.attributes["options"] == ["Laptop", "Kio"]
    assert state.attributes["input_key"] == "hdmi2"


async def test_selecting_a_label_sends_the_key(hass: HomeAssistant) -> None:
    entry = _entry(hass)
    with aioresponses() as m:
        m.get(f"{API}/kiosks", payload=[_office()], repeat=True)
        m.post(f"{API}/kiosks/11111111-1111-1111-1111-111111111111/input", status=204)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": "select.lobby_display_input", "option": "Laptop"},
            blocking=True,
        )
        await hass.async_block_till_done()

        posts = [
            (req.kwargs.get("json"))
            for key, calls in m.requests.items()
            if key[0] == "POST"
            for req in calls
        ]
    assert {"input": "hdmi1"} in posts


async def test_options_follow_meta_changes_without_reload(hass: HomeAssistant) -> None:
    entry = _entry(hass)
    with aioresponses() as m:
        m.get(f"{API}/kiosks", payload=[_office()])
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert hass.states.get("select.lobby_display_input").attributes["options"] == ["Laptop", "Kio"]

        # Admin renames hdmi1 and un-hides dp1 on the kiosk edit page.
        renamed = _office(meta={"input_labels": {"hdmi1": "MacBook", "hdmi2": "Kio"}, "hidden_inputs": ["dp2"]})
        m.get(f"{API}/kiosks", payload=[renamed], repeat=True)
        coordinator = hass.data[DOMAIN][entry.entry_id]
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    assert hass.states.get("select.lobby_display_input").attributes["options"] == ["MacBook", "Kio", "DP 1"]
