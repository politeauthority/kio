# kio Home Assistant integration — backlog

Status of the improvement work referenced from `docs/dev/home-assistant.md`.
The integration polls `GET /kiosks` every 30s via a `DataUpdateCoordinator` and
maps each kiosk to a HA Device. See the dev doc for the development loop.

## Done

### Phase 0 — velocity foundation
- [x] Shared `setup_kio_platform(hass, entry, async_add_entities, factory)` helper
      in `entity.py`; the five platform files collapsed onto it. Adding a platform
      is now a `factory` callback, not ~50 lines of known/_make_*/_on_update.
- [x] One reused `aiohttp.ClientSession` per coordinator (was a new session per
      request), closed in `async_unload_entry`. Writes go through one `_command`
      helper.
- [x] `ha:deploy` switched to `rsync --delete` (removes stale files; scp didn't).
- [x] `task ha:watch` — auto-deploy on file change (needs `watchexec`).
- [x] `task ha:test` + local pytest harness (`pytest-homeassistant-custom-component`
      + `aioresponses`) under `tests/`. No deploy needed to verify entity logic.
- [x] CI runs the harness on changes to `src/ha-integration/`.

### Phase 1 — high-value entities
- [x] Uptime (duration), Hostname, Device Type diagnostic sensors — already in the
      `/kiosks` payload, pure read.
- [x] Brightness `number` (slider, gated on the `brightness` feature; reads
      `meta.brightness`, writes `PUT /kiosks/{id}/brightness`).
- [x] Navigate: `text` entity (reflects/sets current URL) + `kio.navigate` service
      targeting devices/entities/areas. Wires up the previously-dead
      `coordinator.navigate()`.
- [x] Update Agent button (dedicated `POST /kiosks/{id}/agent/update`, not the
      generic `/command` — the server injects the git ref).

## Backlog

### Phase 2 — playlist & tab control
- [ ] Playlist `media_player` (gated on `playlist`): play/stop/next from
      `playlist/play|stop|goto`, state from `playlist_state`. Needs `GET /playlists`
      to populate source options.
- [ ] Tab-cycle `switch` (`tabs/cycle/start|stop`, state from `tab_cycle_state`).
- [ ] Active-tab `select` from `browser_tabs` + `kio.open_tab` / `kio.navigate_tab`
      / `kio.close_tab` services (`browsers` CRUD).

### Phase 3 — distribution
- [ ] Resolution `select` (`set-resolution`) — needs the agent to report available
      modes first.
- [ ] Verify whether the kio API exposes SSE; if so, add a push listener and switch
      `iot_class` to `local_push`.
- [ ] HACS packaging per `docs/research/home-assistant-integration.md`: split to a
      standalone repo (or `content_in_root: false` subdir), `hacs.json`, brand icon,
      official `hassfest` + `hacs/action` validation, first tagged release.

## Notes / gotchas
- Widget-type/feature gating is additive: entities are created when a kiosk first
  appears and when it *gains* a feature flag. Removal is by Device (on kiosk delete),
  handled centrally in `__init__.py` — individual entities aren't torn down on
  feature loss (a stale entity just goes unavailable). Acceptable for now.
- `update_agent` is intentionally NOT in the API's `ALLOWED_COMMANDS`; always use the
  dedicated endpoint so the server picks an API-compatible git ref.

<!-- CI: ha-integration workflow validated on the cicd branch (2026-06-21). -->
