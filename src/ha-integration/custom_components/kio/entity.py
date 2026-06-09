from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import KioCoordinator


class KioEntity(CoordinatorEntity[KioCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: KioCoordinator, kiosk_id: str) -> None:
        super().__init__(coordinator)
        self._kiosk_id = kiosk_id

    @property
    def _kiosk(self) -> dict:
        return self.coordinator.data[self._kiosk_id]

    @property
    def device_info(self) -> DeviceInfo:
        kiosk = self._kiosk
        return DeviceInfo(
            identifiers={(DOMAIN, self._kiosk_id)},
            name=kiosk["name"],
            manufacturer="kio",
            model=kiosk.get("device_type") or "Kiosk",
            sw_version=kiosk.get("agent_version"),
            configuration_url=self.coordinator.api_url,
        )

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self._kiosk_id in self.coordinator.data
