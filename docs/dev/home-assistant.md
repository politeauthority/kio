# Home Assistant Integration — Development

The kio HA integration is a custom component at `src/ha-integration/custom_components/kio/`. It polls `GET /kiosks` every 30 seconds via a `DataUpdateCoordinator` and exposes each kiosk as a HA Device.

For user-facing feature documentation see `docs/features/home-assistant.md`.  
For the improvement backlog and implementation notes see `src/ha-integration/PLAN.md`.

---

## File structure

```
src/ha-integration/custom_components/kio/
├── __init__.py          # entry setup/teardown, platform loading, domain services
├── manifest.json        # HA integration metadata
├── const.py             # DOMAIN, PLATFORMS, config key names
├── coordinator.py       # DataUpdateCoordinator — polls GET /kiosks, sends commands
├── entity.py            # KioEntity base + setup_kio_platform() dynamic-add helper
├── config_flow.py       # UI setup wizard (API URL + key, validates on submit)
├── binary_sensor.py     # Online/offline; Display On (display_power feature)
├── sensor.py            # Status, Current URL, Last Seen, Uptime, Hostname, Device Type, Agent Version, IP
├── button.py            # Reload, Reboot, Detect Capabilities, Update Agent, Standby/Wake (cec)
├── switch.py            # Display Power (display_power feature)
├── select.py            # Display Input (input_switch feature)
├── number.py            # Brightness slider (brightness feature)
├── text.py              # Navigate (set the kiosk's URL)
├── services.yaml        # kio.refresh, kio.navigate
└── translations/
    └── en.json          # Config flow + service labels
```

Tests live alongside at `src/ha-integration/tests/` with `conftest.py`, `pytest.ini`,
and `requirements_test.txt` one level up. See **Local testing** below.

---

## Deploying to Home Assistant

HA runs on a separate machine (`home-assistant` SSH host). Deploy with:

```bash
task ha:deploy
```

This:
1. Strips local `__pycache__` so stale bytecode isn't shipped
2. Wipes and recreates `/config/custom_components/kio/` on the HA host, then `scp`s the integration in — so files deleted locally (e.g. a dropped platform) are also gone on the host. HA OS has no `rsync`, so this is the portable way to get `--delete` semantics with plain `ssh`/`scp`.
3. Runs `ha core restart` — required for any Python code changes to take effect

For a tight edit loop, `task ha:watch` re-runs `ha:deploy` on every save (requires [`watchexec`](https://github.com/watchexec/watchexec)). But prefer the **Local testing** loop below for most logic — it needs no HA host and no restart.

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

## Local testing

The fastest loop — no HA host, no restart. The suite uses
`pytest-homeassistant-custom-component` (which pins a matching HA version and gives
a real in-memory HA core) and `aioresponses` to stub the kio API.

```bash
task ha:test          # uv runs pytest with requirements_test.txt
# or, from src/ha-integration/:
uv run --with-requirements requirements_test.txt pytest -q
```

Tests cover config flow (`tests/test_config_flow.py`) and entity setup including
dynamic feature-gated creation (`tests/test_init.py`). `tests/common.py::make_kiosk`
builds a `/kiosks`-shaped fixture; override any field via kwargs. CI runs this on every
change under `src/ha-integration/` (`.github/workflows/ha-integration.yaml`).

Use this for entity/coordinator logic; fall back to `task ha:deploy` only to confirm
the real environment (DNS, auth, an actual kiosk).

---

## Adding a new entity

Each platform file uses the shared `setup_kio_platform(hass, entry, async_add_entities, factory)`
helper from `entity.py`. You only write a `factory(coordinator, kiosk_id, added, first)`
that returns the entities to create — the helper handles the initial pass, kiosks that
appear later, and kiosks that gain features. `added` is the set of feature flags just
gained; `first` is True the first time a kiosk is seen (use it for always-present entities).

1. Open or create the platform file (`sensor.py`, `number.py`, etc.)
2. Define a class inheriting from `KioEntity` and the HA base (e.g. `SensorEntity`)
3. Set `_attr_unique_id = f"{kiosk_id}_<descriptor>"` — stable across restarts
4. Add it to that file's `factory` (gate on `first` and/or `"<feature>" in added`)
5. If it's a new platform file, add the platform name to `PLATFORMS` in `const.py`
6. Add a test in `tests/` (assert the state appears), then `task ha:deploy` to confirm live

---

## Dynamic entity add/remove

Implemented via `setup_kio_platform` (see above):

- **Added** when new kiosks appear in the coordinator data, or when an existing kiosk gains features (e.g. after Detect Capabilities runs).
- **Removed** at the Device level: when a kiosk is deleted from kio, `__init__.py` removes its Device from the registry, which cascades to its entities. Individual entities are not torn down on feature *loss* — a stale entity just goes unavailable.

---

## Coordinator internals

`KioCoordinator` extends `DataUpdateCoordinator`. On each update it calls `GET /kiosks` and stores the result as `{kiosk_id: kiosk_dict}`. All entities read from `coordinator.data[kiosk_id]` — no entity makes its own HTTP calls.

Command methods (`send_command`, `navigate`, `set_input`, `set_brightness`, `update_agent`) go through one private `_command(method, path, json)` helper that writes to the kio API and then calls `coordinator.async_request_refresh()` to pull updated state immediately. The coordinator reuses a single `aiohttp.ClientSession`, opened lazily and closed in `async_unload_entry`.

`update_agent` is intentionally **not** in the API's `ALLOWED_COMMANDS`; it uses the dedicated `POST /kiosks/{id}/agent/update` so the server injects an API-compatible git ref.

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
| `task ha:test` | Run the local pytest suite (no HA host needed) |
| `task ha:deploy` | rsync integration files to HA host and restart core |
| `task ha:watch` | Auto-deploy on file change (needs watchexec) |
| `ssh home-assistant "ha core logs" \| grep -i kio` | Tail integration logs |
| Settings → Devices & Services → kio → ⋮ → Reload | Reload without full restart (data only) |
| Settings → Devices & Services → kio → Delete | Remove entry (required for breaking config flow changes) |
