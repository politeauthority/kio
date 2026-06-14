from aioresponses import aioresponses
from homeassistant import config_entries, data_entry_flow
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kio.const import CONF_API_KEY, CONF_API_URL, DOMAIN

API = "http://kio.test"


async def test_user_flow_success(hass: HomeAssistant) -> None:
    with aioresponses() as m:
        m.get(f"{API}/kiosks", payload=[], repeat=True)
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] == data_entry_flow.FlowResultType.FORM

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_URL: API}
        )
        await hass.async_block_till_done()

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_API_URL] == API


async def test_user_flow_cannot_connect(hass: HomeAssistant) -> None:
    with aioresponses() as m:
        m.get(f"{API}/kiosks", exception=ConnectionError("boom"))
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_URL: API}
        )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_reconfigure_updates_api_key(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=API, data={CONF_API_URL: API, CONF_API_KEY: "old"}
    )
    entry.add_to_hass(hass)

    with aioresponses() as m:
        m.get(f"{API}/kiosks", payload=[], repeat=True)
        result = await entry.start_reconfigure_flow(hass)
        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "reconfigure"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_URL: API, CONF_API_KEY: "new-key"}
        )
        await hass.async_block_till_done()

    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_API_KEY] == "new-key"
