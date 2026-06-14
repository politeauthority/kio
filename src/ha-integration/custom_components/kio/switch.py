from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import KioCoordinator
from .entity import KioEntity, setup_kio_platform


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    def factory(coordinator: KioCoordinator, kiosk_id: str, added: frozenset, first: bool) -> list:
        entities = []
        if "display_power" in added:
            entities.append(KioDisplaySwitch(coordinator, kiosk_id))
        return entities

    setup_kio_platform(hass, entry, async_add_entities, factory)


class KioDisplaySwitch(KioEntity, SwitchEntity):
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_name = "Display Power"
    _attr_icon = "mdi:monitor"

    def __init__(self, coordinator: KioCoordinator, kiosk_id: str) -> None:
        super().__init__(coordinator, kiosk_id)
        self._attr_unique_id = f"{kiosk_id}_display_power"

    @property
    def is_on(self) -> bool | None:
        return self._kiosk.get("display_on")

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.send_command(self._kiosk_id, "display_on")

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.send_command(self._kiosk_id, "display_off")
