from homeassistant.components.button import ButtonEntity
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

    # known tracks kiosk_id -> frozenset of features we've already created buttons for.
    known: dict[str, frozenset] = {}

    def _make_buttons(kiosk_id: str, features: frozenset, prev_features: frozenset) -> list:
        entities = []
        if kiosk_id not in known:
            entities += [
                KioCommandButton(coordinator, kiosk_id, "reload", "Reload Page", "mdi:refresh"),
                KioCommandButton(coordinator, kiosk_id, "reboot", "Reboot", "mdi:restart"),
                KioCommandButton(coordinator, kiosk_id, "detect_capabilities", "Detect Capabilities", "mdi:magnify"),
            ]
        if "cec" in (features - prev_features):
            entities += [
                KioCommandButton(coordinator, kiosk_id, "standby", "Standby (CEC)", "mdi:monitor-off"),
                KioCommandButton(coordinator, kiosk_id, "wake", "Wake (CEC)", "mdi:monitor"),
            ]
        return entities

    new_entities = []
    for kiosk_id, kiosk in coordinator.data.items():
        features = frozenset(kiosk.get("features", []))
        new_entities.extend(_make_buttons(kiosk_id, features, frozenset()))
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
                new_entities.extend(_make_buttons(kiosk_id, features, prev))
                known[kiosk_id] = features
        for gone in set(known) - current_ids:
            known.pop(gone)
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_on_update))


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
