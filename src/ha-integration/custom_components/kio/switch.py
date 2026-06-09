from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import KioCoordinator
from .entity import KioEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: KioCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: dict[str, frozenset] = {}

    def _make_switches(kiosk_id: str, features: frozenset, prev_features: frozenset) -> list:
        entities = []
        if "display_power" in (features - prev_features):
            entities.append(KioDisplaySwitch(coordinator, kiosk_id))
        return entities

    new_entities = []
    for kiosk_id, kiosk in coordinator.data.items():
        features = frozenset(kiosk.get("features", []))
        new_entities.extend(_make_switches(kiosk_id, features, frozenset()))
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
                new_entities.extend(_make_switches(kiosk_id, features, prev))
                known[kiosk_id] = features
        for gone in set(known) - current_ids:
            known.pop(gone)
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_on_update))


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
