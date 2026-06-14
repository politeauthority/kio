from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
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
        if first:
            entities.append(KioOnlineSensor(coordinator, kiosk_id))
        if "display_power" in added:
            entities.append(KioDisplayOnSensor(coordinator, kiosk_id))
        return entities

    setup_kio_platform(hass, entry, async_add_entities, factory)


class KioOnlineSensor(KioEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_name = "Online"

    def __init__(self, coordinator: KioCoordinator, kiosk_id: str) -> None:
        super().__init__(coordinator, kiosk_id)
        self._attr_unique_id = f"{kiosk_id}_online"

    @property
    def is_on(self) -> bool:
        return self._kiosk.get("status") == "online"


class KioDisplayOnSensor(KioEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.POWER
    _attr_name = "Display On"
    _attr_icon = "mdi:monitor"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: KioCoordinator, kiosk_id: str) -> None:
        super().__init__(coordinator, kiosk_id)
        self._attr_unique_id = f"{kiosk_id}_display_on"

    @property
    def is_on(self) -> bool | None:
        return self._kiosk.get("display_on")
