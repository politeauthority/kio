import logging

import voluptuous as vol
import aiohttp
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.exceptions import HomeAssistantError

from .const import CONF_API_IP, CONF_API_KEY, CONF_API_URL, DOMAIN
from .coordinator import _make_session

_LOGGER = logging.getLogger(__name__)


async def _validate(api_url: str, api_key: str, api_ip: str = "") -> None:
    url = api_url.rstrip("/")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    try:
        async with _make_session(url, api_ip) as session:
            async with session.get(
                f"{url}/kiosks",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 401:
                    raise HomeAssistantError("invalid_auth")
                resp.raise_for_status()
    except HomeAssistantError:
        raise
    except Exception as err:
        _LOGGER.error("kio config flow connection error: %s: %s", type(err).__name__, err)
        raise HomeAssistantError("cannot_connect") from err


class KioConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        errors = {}

        if user_input is not None:
            try:
                await _validate(
                    user_input[CONF_API_URL],
                    user_input.get(CONF_API_KEY, ""),
                    user_input.get(CONF_API_IP, ""),
                )
            except HomeAssistantError as err:
                errors["base"] = str(err)
            else:
                await self.async_set_unique_id(user_input[CONF_API_URL].rstrip("/"))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="kio", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_API_URL, description={"suggested_value": "http://api.kio.example.local"}): str,
                vol.Optional(CONF_API_KEY): str,
                vol.Optional(CONF_API_IP, description={"suggested_value": ""}): str,
            }),
            errors=errors,
        )
