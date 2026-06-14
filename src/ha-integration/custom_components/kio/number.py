from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import KioCoordinator
from .entity import KioEntity, setup_kio_platform


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    def factory(coordinator: KioCoordinator, kiosk_id: str, added: frozenset, first: bool) -> list:
        entities = []
        if "brightness" in added:
            entities.append(KioBrightnessNumber(coordinator, kiosk_id))
        return entities

    setup_kio_platform(hass, entry, async_add_entities, factory)


class KioBrightnessNumber(KioEntity, NumberEntity):
    _attr_name = "Brightness"
    _attr_icon = "mdi:brightness-6"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: KioCoordinator, kiosk_id: str) -> None:
        super().__init__(coordinator, kiosk_id)
        self._attr_unique_id = f"{kiosk_id}_brightness"

    @property
    def native_value(self) -> float | None:
        # Last commanded level is persisted server-side as NodeMeta("brightness")
        # and surfaces in the kiosk's meta dict.
        value = self._kiosk.get("meta", {}).get("brightness")
        return float(value) if value is not None else None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.set_brightness(self._kiosk_id, int(value))
