from homeassistant.components.button import ButtonEntity
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
            entities += [
                KioCommandButton(coordinator, kiosk_id, "reload", "Reload Page", "mdi:refresh"),
                KioCommandButton(coordinator, kiosk_id, "reboot", "Reboot", "mdi:restart"),
                KioCommandButton(coordinator, kiosk_id, "detect_capabilities", "Detect Capabilities", "mdi:magnify"),
                KioUpdateAgentButton(coordinator, kiosk_id),
            ]
        if "cec" in added:
            entities += [
                KioCommandButton(coordinator, kiosk_id, "standby", "Standby (CEC)", "mdi:monitor-off"),
                KioCommandButton(coordinator, kiosk_id, "wake", "Wake (CEC)", "mdi:monitor"),
            ]
        return entities

    setup_kio_platform(hass, entry, async_add_entities, factory)


class KioCommandButton(KioEntity, ButtonEntity):
    def __init__(
        self,
        coordinator: KioCoordinator,
        kiosk_id: str,
        command: str,
        name: str,
        icon: str,
    ) -> None:
        super().__init__(coordinator, kiosk_id)
        self._command = command
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{kiosk_id}_{command}"

    async def async_press(self) -> None:
        await self.coordinator.send_command(self._kiosk_id, self._command)


class KioUpdateAgentButton(KioEntity, ButtonEntity):
    _attr_name = "Update Agent"
    _attr_icon = "mdi:cloud-download"

    def __init__(self, coordinator: KioCoordinator, kiosk_id: str) -> None:
        super().__init__(coordinator, kiosk_id)
        self._attr_unique_id = f"{kiosk_id}_update_agent"

    async def async_press(self) -> None:
        await self.coordinator.update_agent(self._kiosk_id)
