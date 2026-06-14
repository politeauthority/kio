from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import KioCoordinator
from .entity import KioEntity, setup_kio_platform


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    def factory(coordinator: KioCoordinator, kiosk_id: str, added: frozenset, first: bool) -> list:
        if not first:
            return []
        return [KioNavigateText(coordinator, kiosk_id)]

    setup_kio_platform(hass, entry, async_add_entities, factory)


class KioNavigateText(KioEntity, TextEntity):
    _attr_name = "Navigate"
    _attr_icon = "mdi:web-box"
    _attr_native_max = 2048
    _attr_mode = "text"

    def __init__(self, coordinator: KioCoordinator, kiosk_id: str) -> None:
        super().__init__(coordinator, kiosk_id)
        self._attr_unique_id = f"{kiosk_id}_navigate"

    @property
    def native_value(self) -> str | None:
        # Reflects the current URL; setting it navigates the kiosk there.
        return self._kiosk.get("current_url")

    async def async_set_value(self, value: str) -> None:
        await self.coordinator.navigate(self._kiosk_id, value)
