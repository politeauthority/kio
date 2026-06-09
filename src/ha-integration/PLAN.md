# kio Home Assistant Integration — Development Plan

## Current State

The custom component at `src/ha-integration/custom_components/kio/` is functional but incomplete:

- Config flow (URL + optional API key), polling coordinator at 30s
- Entities: online binary_sensor, url/last_seen/agent_version/ip sensors, display switch, input select, command buttons
- Feature-gating for display_power, input_switch, cec already wired

---

## Planned Improvements

### 1. Dynamic entity addition and removal

**Problem:** Entities are created once at `async_setup_entry`. New kiosks registered after HA loads, or kiosks that gain features after `detect_capabilities` runs, don't appear until HA restarts. Likewise, kiosks deleted from the kio database linger as stale devices in HA until a full reload.

**Implementation — addition:**
- Hold a `dict[kiosk_id, frozenset[features]]` of known kiosks in each platform's `async_setup_entry` closure
- Register a coordinator listener (`coordinator.async_add_listener`) that diffs the new data against the known dict
- Call `async_add_entities` with only net-new entities (new kiosk IDs, or existing kiosks with newly gained features)
- Each platform tracks its own state since the entity sets differ by feature flags

**Implementation — removal:**
- When the coordinator update drops a kiosk ID that was previously known, remove it from the tracking dict and clean up HA registries:
  1. **Entity registry** — look up all entities with `(DOMAIN, kiosk_id)` identifier via `er.async_get_entity_id(...)` or `er.entities.get_entries_for_config_entry_id(...)`, then call `er.async_remove(entity_id)` for each
  2. **Device registry** — after entities are removed, look up the device via `dr.async_get_device({(DOMAIN, kiosk_id)})` and call `dr.async_remove_device(device_id)` to fully clear it from HA
- This means a kiosk deleted in kio disappears from HA within one poll cycle (≤30s, or immediately if SSE is implemented)

**Files:** `button.py`, `switch.py`, `select.py`, `sensor.py`, `binary_sensor.py`  
**Imports needed:** `homeassistant.helpers.entity_registry`, `homeassistant.helpers.device_registry`

---

### 2. SSE push updates (real-time state)

**Problem:** 30s polling means display state, current URL, and online status can lag significantly.

**Implementation:**
- Add an `async_setup_sse` method to `KioCoordinator` that opens one `aiohttp` SSE connection per kiosk to `/kiosks/{id}/sse`
- On each SSE event, merge the partial payload into `coordinator.data[kiosk_id]` and call `coordinator.async_set_updated_data(new_data)` — this triggers all entity listeners immediately
- Keep the 30s poll as a fallback for full data refresh (last_seen, ip, agent_version) since SSE only carries the partial heartbeat payload
- Reconnect with exponential backoff on disconnect
- Cancel all SSE tasks in `async_unload_entry`

**Manifest change:** `iot_class` → `"local_push"`

**Files:** `coordinator.py`, `__init__.py`, `manifest.json`

---

### 3. Manual refresh service

**Problem:** No easy way to force a full data refresh from an automation, script, or dev tools without reloading the entire integration.

**Implementation:**
- Register a `kio.refresh` service in `__init__.py` via `hass.services.async_register`
- Service handler calls `coordinator.async_refresh()` on all configured entries
- Optional: accept a `kiosk_id` parameter to refresh a single device

**Service call example:**
```yaml
service: kio.refresh
```

**Files:** `__init__.py`

---

### 4. `display_on` binary sensor

**Problem:** `display_on` is only exposed via the display switch. Automations benefit from having it as a read-only binary_sensor with `BinarySensorDeviceClass.POWER` for use in conditions.

**Implementation:**
- Add `KioDisplaySensor(KioEntity, BinarySensorEntity)` to `binary_sensor.py`
- Only add it when `display_power` is in kiosk features (same gate as the switch)
- `is_on` returns `self._kiosk.get("display_on")`
- `_attr_entity_registry_enabled_default = False` to avoid cluttering the default view

**Files:** `binary_sensor.py`

---

### 5. `status` sensor

**Problem:** The raw `status` string (online/offline/unknown) isn't exposed. Useful for automations that need to distinguish "unknown" from "offline".

**Implementation:**
- Add `KioStatusSensor(KioEntity, SensorEntity)` to `sensor.py`
- `native_value` returns `self._kiosk.get("status")`
- Icon: `mdi:lan-connect`

**Files:** `sensor.py`

---

## Development Workflow

HA runs on a separate machine. The `ha:deploy` task in `Taskfile.yml` handles the full deploy:

```bash
task ha:deploy
```

What it does:
1. `ssh home-assistant "mkdir -p /config/custom_components/kio"` — ensures the target dir exists
2. `scp -r src/ha-integration/custom_components/kio/. home-assistant:/config/custom_components/kio/` — copies all component files
3. `ssh home-assistant "ha core restart"` — restarts HA core to pick up code changes

> **Note:** `scp` does not delete files removed from the source. If you delete a file from the component (e.g. remove a platform), manually remove the stale file on the HA host or consider switching the copy step to `rsync --delete`.

### Config changes during development

When you change the config flow schema (add/remove required fields in `config_flow.py` or `translations/en.json`):

1. Remove the existing config entry in HA (Settings → Devices & Services → kio → Delete)
2. Run `task ha:deploy`
3. Re-add the integration via the UI — the new flow runs against fresh data

For non-breaking config changes (new optional fields with defaults), the existing entry continues to work; new fields are picked up on the next coordinator update after deploy.

---

## Implementation Order

1. `display_on` binary sensor and `status` sensor — low effort, no coordination needed
2. `kio.refresh` service — quick win for manual refresh during dev
3. Dynamic entity addition — moderate; fixes the detect_capabilities UX gap
4. SSE push updates — most complex; do last once the rest is stable
