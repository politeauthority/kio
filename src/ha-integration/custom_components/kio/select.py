from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import KioCoordinator
from .entity import KioEntity

INPUTS = ["hdmi1", "hdmi2", "dp1", "dp2"]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: KioCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: dict[str, frozenset] = {}

    def _make_selects(kiosk_id: str, features: frozenset, prev_features: frozenset) -> list:
        entities = []
        if "input_switch" in (features - prev_features):
            entities.append(KioInputSelect(coordinator, kiosk_id))
        return entities

    new_entities = []
    for kiosk_id, kiosk in coordinator.data.items():
        features = frozenset(kiosk.get("features", []))
        new_entities.extend(_make_selects(kiosk_id, features, frozenset()))
        known[kiosk_id] = features
    async_add_entities(new_entities)

    @callback
    def _on_update() -> None:
        current_ids = set(coordinator.data)
        new_entities = []
        for kiosk_id, kiosk in coordinator.data.items():
            features = frozenset(kiosk.get("features", []))
            prev = known.get(kiosk_id, frozenset())
            if kiosk_id not in known or features != prev:
                new_entities.extend(_make_selects(kiosk_id, features, prev))
                known[kiosk_id] = features
        for gone in set(known) - current_ids:
            known.pop(gone)
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_on_update))


class KioInputSelect(KioEntity, SelectEntity):
    _attr_name = "Display Input"
    _attr_icon = "mdi:video-input-hdmi"
    _attr_options = INPUTS

    def __init__(self, coordinator: KioCoordinator, kiosk_id: str) -> None:
        super().__init__(coordinator, kiosk_id)
        self._attr_unique_id = f"{kiosk_id}_display_input"

    @property
    def current_option(self) -> str | None:
        return self._kiosk.get("current_input")

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.set_input(self._kiosk_id, option)
