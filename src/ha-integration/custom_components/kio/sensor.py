from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.dt import parse_datetime

from .coordinator import KioCoordinator
from .entity import KioEntity, setup_kio_platform


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    def factory(coordinator: KioCoordinator, kiosk_id: str, added: frozenset, first: bool) -> list:
        if not first:
            return []
        return [
            KioStatusSensor(coordinator, kiosk_id),
            KioUrlSensor(coordinator, kiosk_id),
            KioLastSeenSensor(coordinator, kiosk_id),
            KioUptimeSensor(coordinator, kiosk_id),
            KioHostnameSensor(coordinator, kiosk_id),
            KioDeviceTypeSensor(coordinator, kiosk_id),
            KioAgentVersionSensor(coordinator, kiosk_id),
            KioIpAddressSensor(coordinator, kiosk_id),
        ]

    setup_kio_platform(hass, entry, async_add_entities, factory)


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


class KioUptimeSensor(KioEntity, SensorEntity):
    _attr_name = "Uptime"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:timer-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: KioCoordinator, kiosk_id: str) -> None:
        super().__init__(coordinator, kiosk_id)
        self._attr_unique_id = f"{kiosk_id}_uptime"

    @property
    def native_value(self) -> int | None:
        return self._kiosk.get("uptime_seconds")


class KioHostnameSensor(KioEntity, SensorEntity):
    _attr_name = "Hostname"
    _attr_icon = "mdi:console-network"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: KioCoordinator, kiosk_id: str) -> None:
        super().__init__(coordinator, kiosk_id)
        self._attr_unique_id = f"{kiosk_id}_hostname"

    @property
    def native_value(self) -> str | None:
        return self._kiosk.get("hostname")


class KioDeviceTypeSensor(KioEntity, SensorEntity):
    _attr_name = "Device Type"
    _attr_icon = "mdi:raspberry-pi"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: KioCoordinator, kiosk_id: str) -> None:
        super().__init__(coordinator, kiosk_id)
        self._attr_unique_id = f"{kiosk_id}_device_type"

    @property
    def native_value(self) -> str | None:
        return self._kiosk.get("device_type")


class KioAgentVersionSensor(KioEntity, SensorEntity):
    _attr_name = "Agent Version"
    _attr_icon = "mdi:information-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
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
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: KioCoordinator, kiosk_id: str) -> None:
        super().__init__(coordinator, kiosk_id)
        self._attr_unique_id = f"{kiosk_id}_ip_address"

    @property
    def native_value(self) -> str | None:
        return self._kiosk.get("ip_address")
