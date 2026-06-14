from aioresponses import aioresponses
from homeassistant import config_entries, data_entry_flow
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kio.config_flow import CONF_ENV, ENV_PRESETS
from custom_components.kio.const import CONF_API_KEY, CONF_API_URL, DOMAIN

API = "http://kio.test"
PROD = ENV_PRESETS["prod"][CONF_API_URL].rstrip("/")
STG = ENV_PRESETS["staging"][CONF_API_URL].rstrip("/")


async def test_user_flow_custom_env(hass: HomeAssistant) -> None:
    with aioresponses() as m:
        m.get(f"{API}/kiosks", payload=[], repeat=True)
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] == data_entry_flow.FlowResultType.FORM

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ENV: "custom", CONF_API_URL: API}
        )
        await hass.async_block_till_done()

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_API_URL] == API
    assert result["data"][CONF_ENV] == "custom"


async def test_user_flow_prod_preset_fills_url(hass: HomeAssistant) -> None:
    # Choosing the prod environment uses its preset URL — no URL typed.
    with aioresponses() as m:
        m.get(f"{PROD}/kiosks", payload=[], repeat=True)
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ENV: "prod", CONF_API_KEY: "k"}
        )
        await hass.async_block_till_done()

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_API_URL] == PROD
    assert result["title"] == "kio (prod)"


async def test_user_flow_cannot_connect(hass: HomeAssistant) -> None:
    with aioresponses() as m:
        m.get(f"{API}/kiosks", exception=ConnectionError("boom"))
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ENV: "custom", CONF_API_URL: API}
        )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_reconfigure_switches_environment(hass: HomeAssistant) -> None:
    # Start pointed at staging, switch to prod — unique_id + data follow the env.
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=STG,
        data={CONF_ENV: "staging", CONF_API_URL: STG, CONF_API_KEY: "old"},
    )
    entry.add_to_hass(hass)

    with aioresponses() as m:
        m.get(f"{PROD}/kiosks", payload=[], repeat=True)
        result = await entry.start_reconfigure_flow(hass)
        assert result["step_id"] == "reconfigure"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ENV: "prod", CONF_API_KEY: "prod-key"}
        )
        await hass.async_block_till_done()

    assert result["type"] == data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_API_URL] == PROD
    assert entry.data[CONF_ENV] == "prod"
    assert entry.data[CONF_API_KEY] == "prod-key"
    assert entry.unique_id == PROD
