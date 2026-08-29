import logging

import voluptuous as vol
import aiohttp
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import CONF_API_IP, CONF_API_KEY, CONF_API_URL, CONF_CA_CERT, DOMAIN
from .coordinator import _make_session, _ssl_context, ca_cert_path

_LOGGER = logging.getLogger(__name__)

CONF_ENV = "environment"

# Pick an environment and the URL/IP/CA are filled in for you — switching which
# kio instance HA mirrors is then just choosing staging/prod and entering that
# env's API key. Both envs sit behind the same private Traefik gateway
# (host-based routing, plain http redirects to https), so the IP override (needed
# because HA can't resolve the .int hostnames) is shared. The gateway's certs are
# issued by colfax-private-ca, which HA's Python trust store doesn't know — the CA
# PEM lives in the HA config dir and is trusted alongside the system CAs.
CA_CERT_PRESET = "certs/colfax-private-ca.crt"
ENV_PRESETS: dict[str, dict[str, str]] = {
    "staging": {
        CONF_API_URL: "https://api.stg.kio.colfax.int",
        CONF_API_IP: "192.168.50.85",
        CONF_CA_CERT: CA_CERT_PRESET,
    },
    "prod": {
        CONF_API_URL: "https://api.kio.colfax.int",
        CONF_API_IP: "192.168.50.85",
        CONF_CA_CERT: CA_CERT_PRESET,
    },
}
ENV_CHOICES = ["prod", "staging", "custom"]


async def _validate(
    hass: HomeAssistant, api_url: str, api_key: str, api_ip: str = "", ca_cert: str = ""
) -> None:
    url = api_url.rstrip("/")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    try:
        ssl_context = await hass.async_add_executor_job(_ssl_context, ca_cert_path(hass, ca_cert))
        async with _make_session(url, api_ip, ssl_context) as session:
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


def _resolve(user_input: dict) -> dict[str, str]:
    """Entry data from the form: a chosen env applies its preset (URL, IP, CA);
    `custom` uses the typed values."""
    env = user_input.get(CONF_ENV, "custom")
    preset = ENV_PRESETS.get(env)
    if preset:
        url, ip, ca = preset[CONF_API_URL], preset[CONF_API_IP], preset[CONF_CA_CERT]
    else:
        url = (user_input.get(CONF_API_URL) or "").strip()
        ip = (user_input.get(CONF_API_IP) or "").strip()
        ca = (user_input.get(CONF_CA_CERT) or "").strip()
    return {
        CONF_ENV: env,
        CONF_API_URL: url.rstrip("/"),
        CONF_API_KEY: user_input.get(CONF_API_KEY, ""),
        CONF_API_IP: ip,
        CONF_CA_CERT: ca,
    }


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
        vol.Optional(CONF_CA_CERT, description={"suggested_value": defaults.get(CONF_CA_CERT, "")}): str,
    })


def _title(env: str) -> str:
    return f"kio ({env})" if env in ENV_PRESETS else "kio"


class KioConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            data = _resolve(user_input)
            url = data[CONF_API_URL]
            if not url:
                errors["base"] = "url_required"
            else:
                try:
                    await _validate(self.hass, url, data[CONF_API_KEY], data[CONF_API_IP], data[CONF_CA_CERT])
                except HomeAssistantError as err:
                    errors["base"] = str(err)
                else:
                    await self.async_set_unique_id(url)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(title=_title(data[CONF_ENV]), data=data)

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
            data = _resolve(user_input)
            url = data[CONF_API_URL]
            if not url:
                errors["base"] = "url_required"
            else:
                try:
                    await _validate(self.hass, url, data[CONF_API_KEY], data[CONF_API_IP], data[CONF_CA_CERT])
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
                        entry, title=_title(data[CONF_ENV]), unique_id=url, data=data
                    )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(user_input or {**entry.data, CONF_ENV: _env_of(entry.data)}),
            errors=errors,
        )
