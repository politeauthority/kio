import logging

import voluptuous as vol
import aiohttp
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.exceptions import HomeAssistantError

from .const import CONF_API_IP, CONF_API_KEY, CONF_API_URL, DOMAIN
from .coordinator import _make_session

_LOGGER = logging.getLogger(__name__)

CONF_ENV = "environment"

# Pick an environment and the URL/IP are filled in for you — switching which kio
# instance HA mirrors is then just choosing staging/prod and entering that env's
# API key. Both envs sit behind the same private gateway (host-based routing), so
# the IP override (needed because HA can't resolve the .int hostnames) is shared.
ENV_PRESETS: dict[str, dict[str, str]] = {
    "staging": {CONF_API_URL: "http://api.stg.kio.colfax.int", CONF_API_IP: "192.168.50.81"},
    "prod":    {CONF_API_URL: "http://api.kio.colfax.int",     CONF_API_IP: "192.168.50.81"},
}
ENV_CHOICES = ["prod", "staging", "custom"]


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


def _resolve(user_input: dict) -> tuple[str, str, str]:
    """(api_url, api_key, api_ip) from the form: a chosen env applies its preset;
    `custom` uses the typed URL/IP."""
    preset = ENV_PRESETS.get(user_input.get(CONF_ENV, "custom"))
    if preset:
        url, ip = preset[CONF_API_URL], preset[CONF_API_IP]
    else:
        url = (user_input.get(CONF_API_URL) or "").strip()
        ip = (user_input.get(CONF_API_IP) or "").strip()
    return url.rstrip("/"), user_input.get(CONF_API_KEY, ""), ip


def _env_of(data: dict) -> str:
    """Which environment an existing entry points at, for pre-selecting the form."""
    if data.get(CONF_ENV):
        return data[CONF_ENV]
    url = (data.get(CONF_API_URL) or "").rstrip("/")
    for name, preset in ENV_PRESETS.items():
        if preset[CONF_API_URL].rstrip("/") == url:
            return name
    return "custom"


def _schema(defaults: dict | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema({
        vol.Required(CONF_ENV, default=defaults.get(CONF_ENV, "prod")): vol.In(ENV_CHOICES),
        vol.Optional(CONF_API_KEY, description={"suggested_value": defaults.get(CONF_API_KEY, "")}): str,
        vol.Optional(CONF_API_URL, description={"suggested_value": defaults.get(CONF_API_URL, "")}): str,
        vol.Optional(CONF_API_IP, description={"suggested_value": defaults.get(CONF_API_IP, "")}): str,
    })


def _title(env: str) -> str:
    return f"kio ({env})" if env in ENV_PRESETS else "kio"


class KioConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            url, key, ip = _resolve(user_input)
            env = user_input.get(CONF_ENV, "custom")
            if not url:
                errors["base"] = "url_required"
            else:
                try:
                    await _validate(url, key, ip)
                except HomeAssistantError as err:
                    errors["base"] = str(err)
                else:
                    await self.async_set_unique_id(url)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=_title(env),
                        data={CONF_ENV: env, CONF_API_URL: url, CONF_API_KEY: key, CONF_API_IP: ip},
                    )

        return self.async_show_form(step_id="user", data_schema=_schema(), errors=errors)

    async def async_step_reconfigure(self, user_input=None) -> ConfigFlowResult:
        """Re-point this integration at a different kio environment, or fix its key.

        Switching staging<->prod intentionally changes which instance HA mirrors
        (and thus the entry's unique_id), so — unlike a normal reconfigure — this
        allows the unique_id to change; it only blocks colliding with a *different*
        already-configured entry.
        """
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            url, key, ip = _resolve(user_input)
            env = user_input.get(CONF_ENV, "custom")
            if not url:
                errors["base"] = "url_required"
            else:
                try:
                    await _validate(url, key, ip)
                except HomeAssistantError as err:
                    errors["base"] = str(err)
                else:
                    collision = any(
                        e.entry_id != entry.entry_id and (e.unique_id or "") == url
                        for e in self._async_current_entries()
                    )
                    if collision:
                        return self.async_abort(reason="already_configured")
                    await self.async_set_unique_id(url)
                    return self.async_update_reload_and_abort(
                        entry,
                        title=_title(env),
                        unique_id=url,
                        data={CONF_ENV: env, CONF_API_URL: url, CONF_API_KEY: key, CONF_API_IP: ip},
                    )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(user_input or {**entry.data, CONF_ENV: _env_of(entry.data)}),
            errors=errors,
        )
