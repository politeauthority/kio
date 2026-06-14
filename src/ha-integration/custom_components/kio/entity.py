from collections.abc import Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import KioCoordinator

# A factory turns (coordinator, kiosk_id, added_features, first_seen) into the
# entities a platform wants to create for a kiosk on this pass.
#   added_features — feature flags this kiosk just gained (features - prev). On
#                    first sight this is the kiosk's full feature set.
#   first_seen     — True the first time we see this kiosk; use it to create the
#                    "always present" entities exactly once.
EntityFactory = Callable[[KioCoordinator, str, frozenset, bool], list]


def setup_kio_platform(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    factory: EntityFactory,
) -> None:
    """Wire a platform's entities to the coordinator with dynamic-add support.

    Replaces the per-file known/_make_*/_on_update boilerplate. Entities are
    created for kiosks present now, for kiosks that appear later, and for kiosks
    that gain new feature flags (e.g. after Detect Capabilities runs). Device
    removal on kiosk deletion is handled centrally in __init__.py.
    """
    coordinator: KioCoordinator = hass.data[DOMAIN][entry.entry_id]
    # kiosk_id -> feature flags we've already built entities for.
    known: dict[str, frozenset] = {}

    def _collect() -> list:
        new: list = []
        current = coordinator.data
        for kiosk_id, kiosk in current.items():
            features = frozenset(kiosk.get("features", []))
            first = kiosk_id not in known
            prev = known.get(kiosk_id, frozenset())
            if first or features != prev:
                new += factory(coordinator, kiosk_id, features - prev, first)
                known[kiosk_id] = features
        for gone in set(known) - set(current):
            known.pop(gone)
        return new

    async_add_entities(_collect())

    @callback
    def _on_update() -> None:
        new = _collect()
        if new:
            async_add_entities(new)

    entry.async_on_unload(coordinator.async_add_listener(_on_update))


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
