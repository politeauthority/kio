import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, PLATFORMS
from .coordinator import KioCoordinator

NAVIGATE_SCHEMA = vol.Schema(
    {
        vol.Required("url"): cv.string,
        vol.Optional("device_id"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("entity_id"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("area_id"): vol.All(cv.ensure_list, [cv.string]),
    }
)


def _kiosk_id_for_device(dev_reg: dr.DeviceRegistry, device_id: str) -> str | None:
    device = dev_reg.async_get(device_id)
    if not device:
        return None
    for domain, ident in device.identifiers:
        if domain == DOMAIN:
            return ident
    return None


def _coordinator_for(hass: HomeAssistant, kiosk_id: str) -> KioCoordinator | None:
    for coord in hass.data.get(DOMAIN, {}).values():
        if kiosk_id in coord.data:
            return coord
    return None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = KioCoordinator(hass, entry)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        # First refresh failed (e.g. ConfigEntryNotReady on a 401/unreachable
        # API). Setup won't complete, so async_unload_entry never runs — close
        # the session here or it leaks on every retry.
        await coordinator.async_close()
        raise
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register domain services once, not once per config entry.
    if not hass.services.has_service(DOMAIN, "refresh"):
        async def _handle_refresh(call: ServiceCall) -> None:
            for coord in hass.data.get(DOMAIN, {}).values():
                await coord.async_refresh()
        hass.services.async_register(DOMAIN, "refresh", _handle_refresh)

    if not hass.services.has_service(DOMAIN, "navigate"):
        async def _handle_navigate(call: ServiceCall) -> None:
            url = call.data["url"]
            dev_reg = dr.async_get(hass)
            ent_reg = er.async_get(hass)
            device_ids: set[str] = set(call.data.get("device_id", []))
            for entity_id in call.data.get("entity_id", []):
                ent = ent_reg.async_get(entity_id)
                if ent and ent.device_id:
                    device_ids.add(ent.device_id)
            for area_id in call.data.get("area_id", []):
                for device in dr.async_entries_for_area(dev_reg, area_id):
                    device_ids.add(device.id)
            for device_id in device_ids:
                kiosk_id = _kiosk_id_for_device(dev_reg, device_id)
                if not kiosk_id:
                    continue
                coord = _coordinator_for(hass, kiosk_id)
                if coord:
                    await coord.navigate(kiosk_id, url)
        hass.services.async_register(DOMAIN, "navigate", _handle_navigate, schema=NAVIGATE_SCHEMA)

    # Remove devices from the device registry when kiosks are deleted from kio.
    # Removing a device cascades to entity registry cleanup automatically.
    known_kiosk_ids: set[str] = set(coordinator.data)

    @callback
    def _handle_kiosk_removal() -> None:
        current_ids = set(coordinator.data)
        removed_ids = known_kiosk_ids - current_ids
        known_kiosk_ids.clear()
        known_kiosk_ids.update(current_ids)
        if not removed_ids:
            return
        device_reg = dr.async_get(hass)
        for kiosk_id in removed_ids:
            device = device_reg.async_get_device(identifiers={(DOMAIN, kiosk_id)})
            if device:
                device_reg.async_remove_device(device.id)

    entry.async_on_unload(coordinator.async_add_listener(_handle_kiosk_removal))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: KioCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_close()
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, "refresh")
            hass.services.async_remove(DOMAIN, "navigate")
    return unload_ok
