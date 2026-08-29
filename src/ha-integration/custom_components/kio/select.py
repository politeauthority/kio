from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import KioCoordinator
from .entity import KioEntity, setup_kio_platform

# Every input a node can be asked to switch to, in display order, with the label
# used when the kiosk's admin hasn't named it. Mirrors ALL_INPUTS in the dashboard.
INPUTS: list[tuple[str, str]] = [
    ("hdmi1", "HDMI 1"),
    ("hdmi2", "HDMI 2"),
    ("dp1", "DP 1"),
    ("dp2", "DP 2"),
]


def input_options(kiosk: dict) -> dict[str, str]:
    """The inputs to offer for a kiosk, as {label: key}, honouring the dashboard's
    Input Configuration: `meta.hidden_inputs` drops an input, `meta.input_labels`
    renames it. The input the display is on right now is always included, even
    when hidden, so the entity's state never goes unknown for a real input.

    Labels are what Home Assistant shows and what a dashboard dropdown lists, so
    they double as the option value; a label used for two inputs gets the key
    appended to stay unambiguous.
    """
    meta = kiosk.get("meta") or {}
    labels = meta.get("input_labels") or {}
    hidden = set(meta.get("hidden_inputs") or [])
    current = kiosk.get("current_input")

    options: dict[str, str] = {}
    for key, default in INPUTS:
        if key in hidden and key != current:
            continue
        label = (labels.get(key) or "").strip() or default
        if label in options:
            label = f"{label} ({key})"
        options[label] = key
    return options


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    def factory(coordinator: KioCoordinator, kiosk_id: str, added: frozenset, first: bool) -> list:
        entities = []
        if "input_switch" in added:
            entities.append(KioInputSelect(coordinator, kiosk_id))
        return entities

    setup_kio_platform(hass, entry, async_add_entities, factory)


class KioInputSelect(KioEntity, SelectEntity):
    _attr_name = "Display Input"
    _attr_icon = "mdi:video-input-hdmi"

    def __init__(self, coordinator: KioCoordinator, kiosk_id: str) -> None:
        super().__init__(coordinator, kiosk_id)
        self._attr_unique_id = f"{kiosk_id}_display_input"

    @property
    def options(self) -> list[str]:
        # Computed on every read so a rename or hide on the dashboard shows up on
        # the next poll without a reload.
        return list(input_options(self._kiosk))

    @property
    def current_option(self) -> str | None:
        current = self._kiosk.get("current_input")
        if not current:
            return None
        for label, key in input_options(self._kiosk).items():
            if key == current:
                return label
        return None

    @property
    def extra_state_attributes(self) -> dict:
        # The raw key behind the current option, for automations that want it.
        return {"input_key": self._kiosk.get("current_input")}

    async def async_select_option(self, option: str) -> None:
        key = input_options(self._kiosk).get(option)
        if key is None:
            raise ValueError(f"{option!r} is not an available input for this kiosk")
        await self.coordinator.set_input(self._kiosk_id, key)
