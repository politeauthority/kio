from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
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

    # known tracks kiosk_id -> frozenset of features we've already created entities for.
    known: dict[str, frozenset] = {}

    def _make_entities(kiosk_id: str, features: frozenset, prev_features: frozenset) -> list:
        entities = []
        if kiosk_id not in known:
            entities.append(KioOnlineSensor(coordinator, kiosk_id))
        if "display_power" in (features - prev_features):
            entities.append(KioDisplayOnSensor(coordinator, kiosk_id))
        return entities

    new_entities = []
    for kiosk_id, kiosk in coordinator.data.items():
        features = frozenset(kiosk.get("features", []))
        new_entities.extend(_make_entities(kiosk_id, features, frozenset()))
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
                new_entities.extend(_make_entities(kiosk_id, features, prev))
                known[kiosk_id] = features
        for gone in set(known) - current_ids:
            known.pop(gone)
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_on_update))


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
