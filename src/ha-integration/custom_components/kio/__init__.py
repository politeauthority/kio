from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, PLATFORMS
from .coordinator import KioCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = KioCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register the refresh service once per domain, not once per config entry.
    if not hass.services.has_service(DOMAIN, "refresh"):
        async def _handle_refresh(call: ServiceCall) -> None:
            for coord in hass.data.get(DOMAIN, {}).values():
                await coord.async_refresh()
        hass.services.async_register(DOMAIN, "refresh", _handle_refresh)

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
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, "refresh")
    return unload_ok
