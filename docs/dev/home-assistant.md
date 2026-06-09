# Home Assistant Integration — Development

The kio HA integration is a custom component at `src/ha-integration/custom_components/kio/`. It polls `GET /kiosks` every 30 seconds via a `DataUpdateCoordinator` and exposes each kiosk as a HA Device.

For user-facing feature documentation see `docs/features/home-assistant.md`.  
For the improvement backlog and implementation notes see `src/ha-integration/PLAN.md`.

---

## File structure

```
src/ha-integration/custom_components/kio/
├── __init__.py          # entry setup/teardown, platform loading
├── manifest.json        # HA integration metadata
├── const.py             # DOMAIN, PLATFORMS, config key names
├── coordinator.py       # DataUpdateCoordinator — polls GET /kiosks, sends commands
├── entity.py            # KioEntity base class — device_info, availability
├── config_flow.py       # UI setup wizard (API URL + key, validates on submit)
├── binary_sensor.py     # Online/offline
├── sensor.py            # Current URL, Last Seen, Agent Version, IP Address
├── button.py            # Reload, Reboot, Detect Capabilities, Standby, Wake
├── switch.py            # Display Power (conditional on display_power feature)
├── select.py            # Display Input (conditional on input_switch feature)
└── translations/
    └── en.json          # Config flow labels and error strings
```

---

## Deploying to Home Assistant

HA runs on a separate machine (`home-assistant` SSH host). Deploy with:

```bash
task ha:deploy
```

This:
1. Creates `/config/custom_components/kio/` on the HA host if it doesn't exist
2. Copies all files from `src/ha-integration/custom_components/kio/` via `scp`
3. Runs `ha core restart` — required for any Python code changes to take effect

> `scp` does not remove files that were deleted locally. If you remove a platform file, delete the stale copy on the HA host manually, or switch the copy step to `rsync --delete`.

---

## Development loop

1. Edit files under `src/ha-integration/custom_components/kio/`
2. `task ha:deploy` — copies and restarts
3. Check logs (see below)
4. Repeat

For pure data/state changes (coordinator tweaks, entity attribute values), a full restart is always safest. For config flow changes that add required fields, remove and re-add the integration entry (see below).

---

## Checking logs

```bash
ssh home-assistant "ha core logs" | grep -i kio
```

Or in the HA UI: **Settings → System → Logs → Load Full Logs**, filter for `kio`.

---

## First-time setup in HA

After the first `task ha:deploy` and HA restart:

1. **Settings → Devices & Services → Add Integration**
2. Search for **kio**
3. Enter:
   - **API URL** — e.g. `http://api.kio.example.local`
   - **API Key** — leave blank if auth is disabled
4. Submit — HA validates by calling `GET /kiosks`

All registered kiosks appear as Devices immediately.

---

## Config flow changes

When you add or remove **required** fields in `config_flow.py` or `translations/en.json`:

1. Delete the existing integration entry in HA (**Settings → Devices & Services → kio → Delete**)
2. `task ha:deploy`
3. Re-add via **Add Integration → kio**

For **optional** fields with defaults, the existing entry continues to work and the new field is picked up on the next coordinator refresh after deploy.

---

## Adding a new entity

1. Open or create the appropriate platform file (`sensor.py`, `binary_sensor.py`, etc.)
2. Define a class inheriting from both `KioEntity` and the HA entity base (e.g. `SensorEntity`)
3. Set `_attr_unique_id = f"{kiosk_id}_<descriptor>"` — must be stable across restarts
4. If it's a new platform file, add the platform name to `PLATFORMS` in `const.py`
5. Add the entity to the `async_setup_entry` list in that platform file
6. `task ha:deploy` and verify under **Settings → Devices & Services → kio → your device**

---

## Dynamic entity add/remove

Currently entities are created once at startup. The planned improvement (see `PLAN.md`) will:

- **Add** entities when new kiosks appear in the coordinator data, or when an existing kiosk gains features (e.g. after Detect Capabilities runs)
- **Remove** entities and their parent Device from the HA entity and device registries when a kiosk is deleted from kio

Until that's implemented, adding or deleting kiosks requires reloading the integration (**Settings → Devices & Services → kio → ⋮ → Reload**) or running `task ha:deploy`.

---

## Coordinator internals

`KioCoordinator` extends `DataUpdateCoordinator`. On each update it calls `GET /kiosks` and stores the result as `{kiosk_id: kiosk_dict}`. All entities read from `coordinator.data[kiosk_id]` — no entity makes its own HTTP calls.

Command methods (`send_command`, `navigate`, `set_input`) post to the kio API and then call `coordinator.async_request_refresh()` to pull updated state immediately.

If `_async_update_data` raises `UpdateFailed`, HA marks all entities unavailable and retries on the next 30-second interval.

---

## Debugging in the HA UI

Navigate to these pages to verify integration state. All paths are relative to `https://ha.squid-ink.us`.

| What you want to see | Navigation path |
|---|---|
| kio integration card (devices, errors) | **Settings → Devices & Services** → scroll to the kio card |
| All kio devices | **Settings → Devices & Services → Devices** tab → filter by `kio` |
| All kio entities and their current state | **Settings → Devices & Services → Entities** tab → filter by `kio` |
| A single kiosk's full entity list | Click any kio device → see all entities on that device page |
| All entity state values (raw) | **Developer Tools → States** → filter field: `kio` |
| Call `kio.refresh` manually | **Developer Tools → Actions** → search for `kio.refresh` → Call Action |
| Integration errors / load failures | **Settings → System → Logs** → search `kio` |
| Coordinator poll errors | **Settings → System → Logs** → search `coordinator` or `UpdateFailed` |

> The **States** page under Developer Tools is the fastest way to confirm a kiosk's data is flowing — every entity and its raw value is visible there without clicking into individual devices.

---

## Quick reference

| Task / command | What it does |
|---|---|
| `task ha:deploy` | Copy integration files to HA host and restart core |
| `ssh home-assistant "ha core logs" \| grep -i kio` | Tail integration logs |
| Settings → Devices & Services → kio → ⋮ → Reload | Reload without full restart (data only) |
| Settings → Devices & Services → kio → Delete | Remove entry (required for breaking config flow changes) |
