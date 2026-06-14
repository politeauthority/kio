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


def _schema(defaults: dict | None = None) -> vol.Schema:
    """Build the connection form, pre-filling from `defaults` when reconfiguring."""
    defaults = defaults or {}
    return vol.Schema({
        vol.Required(
            CONF_API_URL,
            description={"suggested_value": defaults.get(CONF_API_URL, "http://api.kio.example.local")},
        ): str,
        vol.Optional(
            CONF_API_KEY,
            description={"suggested_value": defaults.get(CONF_API_KEY, "")},
        ): str,
        vol.Optional(
            CONF_API_IP,
            description={"suggested_value": defaults.get(CONF_API_IP, "")},
        ): str,
    })


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

        return self.async_show_form(step_id="user", data_schema=_schema(), errors=errors)

    async def async_step_reconfigure(self, user_input=None) -> ConfigFlowResult:
        """Update an existing entry's connection settings (e.g. a rotated API key).

        Lets you fix credentials without deleting and re-adding the integration.
        """
        entry = self._get_reconfigure_entry()
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
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(entry, data_updates=user_input)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(user_input or entry.data),
            errors=errors,
        )
