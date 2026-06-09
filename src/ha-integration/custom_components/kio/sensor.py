from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.dt import parse_datetime

from .const import DOMAIN
from .coordinator import KioCoordinator
from .entity import KioEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: KioCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: set[str] = set()

    def _make_sensors(kiosk_id: str) -> list:
        return [
            KioStatusSensor(coordinator, kiosk_id),
            KioUrlSensor(coordinator, kiosk_id),
            KioLastSeenSensor(coordinator, kiosk_id),
            KioAgentVersionSensor(coordinator, kiosk_id),
            KioIpAddressSensor(coordinator, kiosk_id),
        ]

    new_entities = [s for kid in coordinator.data for s in _make_sensors(kid)]
    known.update(coordinator.data)
    async_add_entities(new_entities)

    @callback
    def _on_update() -> None:
        current_ids = set(coordinator.data)
        new_ids = current_ids - known
        new_entities = [s for kid in new_ids for s in _make_sensors(kid)]
        known.update(new_ids)
        known.intersection_update(current_ids)
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_on_update))


class KioStatusSensor(KioEntity, SensorEntity):
    _attr_name = "Status"
    _attr_icon = "mdi:lan-connect"

    def __init__(self, coordinator: KioCoordinator, kiosk_id: str) -> None:
        super().__init__(coordinator, kiosk_id)
        self._attr_unique_id = f"{kiosk_id}_status"

    @property
    def native_value(self) -> str | None:
        return self._kiosk.get("status")


class KioUrlSensor(KioEntity, SensorEntity):
    _attr_name = "Current URL"
    _attr_icon = "mdi:web"

    def __init__(self, coordinator: KioCoordinator, kiosk_id: str) -> None:
        super().__init__(coordinator, kiosk_id)
        self._attr_unique_id = f"{kiosk_id}_current_url"

    @property
    def native_value(self) -> str | None:
        return self._kiosk.get("current_url")


class KioLastSeenSensor(KioEntity, SensorEntity):
    _attr_name = "Last Seen"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-outline"

    def __init__(self, coordinator: KioCoordinator, kiosk_id: str) -> None:
        super().__init__(coordinator, kiosk_id)
        self._attr_unique_id = f"{kiosk_id}_last_seen"

    @property
    def native_value(self):
        raw = self._kiosk.get("last_seen")
        return parse_datetime(raw) if raw else None


class KioAgentVersionSensor(KioEntity, SensorEntity):
    _attr_name = "Agent Version"
    _attr_icon = "mdi:information-outline"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: KioCoordinator, kiosk_id: str) -> None:
        super().__init__(coordinator, kiosk_id)
        self._attr_unique_id = f"{kiosk_id}_agent_version"

    @property
    def native_value(self) -> str | None:
        return self._kiosk.get("agent_version")


class KioIpAddressSensor(KioEntity, SensorEntity):
    _attr_name = "IP Address"
    _attr_icon = "mdi:ip-network"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: KioCoordinator, kiosk_id: str) -> None:
        super().__init__(coordinator, kiosk_id)
        self._attr_unique_id = f"{kiosk_id}_ip_address"

    @property
    def native_value(self) -> str | None:
        return self._kiosk.get("ip_address")
