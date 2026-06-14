from aioresponses import aioresponses
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kio.const import CONF_API_URL, DOMAIN

from .common import make_kiosk

API = "http://kio.test"


def _entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_API_URL: API})
    entry.add_to_hass(hass)
    return entry


async def test_base_entities_created(hass: HomeAssistant) -> None:
    entry = _entry(hass)
    with aioresponses() as m:
        m.get(f"{API}/kiosks", payload=[make_kiosk()], repeat=True)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # Always-present entities.
    online = hass.states.get("binary_sensor.lobby_online")
    assert online is not None and online.state == "on"
    assert hass.states.get("sensor.lobby_status").state == "online"
    assert hass.states.get("sensor.lobby_uptime").state == "3600"
    # Feature-gated brightness should NOT exist without the flag.
    assert hass.states.get("number.lobby_brightness") is None


async def test_feature_gated_entities_appear_dynamically(hass: HomeAssistant) -> None:
    entry = _entry(hass)
    with aioresponses() as m:
        # First poll: no brightness feature.
        m.get(f"{API}/kiosks", payload=[make_kiosk()])
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert hass.states.get("number.lobby_brightness") is None

        # Second poll: kiosk gains the brightness feature (e.g. after detect).
        m.get(
            f"{API}/kiosks",
            payload=[make_kiosk(features=["brightness"], meta={"brightness": 42})],
            repeat=True,
        )
        coordinator = hass.data[DOMAIN][entry.entry_id]
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    brightness = hass.states.get("number.lobby_brightness")
    assert brightness is not None
    assert float(brightness.state) == 42.0
