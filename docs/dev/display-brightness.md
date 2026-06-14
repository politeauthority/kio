# Display Brightness (proposed)

How a kiosk's display **brightness** would be read and set from the dashboard — a
per-node luminance dimmer, distinct from the existing on/off/standby **power**
controls — shipped first behind a **feature gate** that nodes consume and refresh
live.

> Status: **implemented.** Ships behind the `brightness_enabled` gate (default
> off). Mirrors the existing `set_input` (VCP 60) / display-power (VCP D6) paths
> plus the per-node **agent-settings** delivery used by display resolution — see
> `docs/dev/display-resolution.md` and `docs/dev/feature-flags.md`.
>
> Two deviations from the original design, both to keep scope tight:
> - **No `current_brightness` heartbeat / DB column.** The dashboard slider
>   initializes from the last commanded value persisted as `NodeMeta("brightness")`
>   (already returned in `KioskRead.meta`), so no new column, schema, or SSE field
>   was needed. Live hardware read-back (`getvcp 10`) was dropped as marginal.
> - **No migration.** Both `app_settings` and `node_meta` are existing key/value
>   tables, and `get_global_settings` already falls back to `AGENT_SETTING_DEFAULTS`
>   for unseeded keys (gate default `0` = off), so no seed row is required.

## Why this is a small addition

Brightness on a DDC/CI monitor is just **another VCP code — `10` (luminance,
0–100)** — read/written exactly like the two VCP codes the agent already drives:

| Capability     | VCP  | Read                  | Write                         |
|----------------|------|-----------------------|-------------------------------|
| `display_power`| `D6` | `ddcutil getvcp D6`   | `ddcutil setvcp D6 <1\|2\|4>` |
| `input_switch` | `60` | `ddcutil getvcp 60`   | `ddcutil setvcp 60 <hex>`     |
| **`brightness`** (new) | `10` | `ddcutil getvcp 10` | `ddcutil setvcp 10 <0–100>`   |

No new transport, no new daemon, no new sudoers entry (ddcutil already runs without
sudo on these nodes). The two genuinely new pieces are: a **feature gate that
reaches the node**, and **per-node configuration** of the gate and default value.

## Two requirements that drive the design

1. **Per-node configurable** — each kiosk can be enabled and tuned independently.
2. **Released behind a feature gate first**, where **nodes consume the gate and
   refresh it live when it changes** (not on the next reboot).

These two requirements rule out kio's `feature_flags` table and point squarely at the
**agent-settings** system. The next section explains why.

## Pick the right gate: agent-settings, NOT `feature_flags`

kio has two config systems. Only one fits:

| | `feature_flags` table | **agent settings** (`/agent/settings`) |
|---|---|---|
| Scope | **Global**, same for everyone | **Global default + per-node override** |
| Reaches the node? | **No** — UI-only, hides dashboard elements | **Yes** — agent pulls it |
| Refresh on change | Next dashboard page load | **Boot + `settings_checkin_seconds` + immediate `sync_settings` push** |
| Per-kiosk? | No (doc: "not per-user or per-kiosk gating") | **Yes** (`settings_overrides` NodeMeta) |

Because the requirement is *per-node* + *node-consumed* + *live-refreshed*, the gate
**must ride agent settings**. `feature_flags` is the wrong mechanism here — its own doc
states it's global and "only hides UI; the API endpoints behind a feature stay
reachable," and it never propagates to nodes.

> Optional extra: a *cosmetic* `feature_flags` entry (`brightness`) may additionally
> hide the whole dashboard section during early development. That's purely a
> dashboard-side dark-launch convenience and is **not** the authoritative gate the
> nodes honor. Don't make it the source of truth.

### The gate + value as agent settings

Add two keys to the agent-settings system (`src/api/app/services/settings_service.py`):

```python
AGENT_SETTING_DEFAULTS = {
    ...,
    "brightness_enabled": 0,    # feature gate: 0 = off (dark launch at release)
    "brightness_default": 80,   # luminance applied when enabled, 0–100
}
SETTING_BOUNDS = {
    ...,
    "brightness_enabled": (0, 1),
    "brightness_default": (0, 100),
}
# A single node may enable/tune brightness independent of the global default:
OVERRIDABLE_KEYS = { ..., "brightness_enabled", "brightness_default" }
# Flipping either must bounce the fleet so nodes re-pull and apply live:
NODE_AFFECTING_KEYS = { ..., "brightness_enabled", "brightness_default" }
```

(The agent-settings system is integer-typed with bounds, so the gate is modelled as a
`0/1` int — it slots into `coerce_setting`/`SETTING_BOUNDS` with zero new typing
machinery.)

### How "nodes refresh the gate when changed" already works

This is the existing settings-refresh machinery; routing the gate through it means we
get live refresh for free:

```
Global flip:   PUT /settings/agent {brightness_enabled:1}
                 └─ update_global_settings → changed ∩ NODE_AFFECTING_KEYS
                    └─ _notify_all_nodes() → publish sync_settings to EVERY kiosk

Per-node flip: PUT /kiosks/{id}/meta/settings_overrides {brightness_enabled:1}
                 └─ set_meta → META_SYNC_COMMANDS["settings_overrides"]
                    └─ publish sync_settings to THAT kiosk only

On the node:   sync_settings ──▶ _sync_settings() ──▶ _apply_settings(report=False)
               also: boot, and _settings_loop every settings_checkin_seconds
                 └─ GET /agent/settings  (effective = globals merged with overrides)
                 └─ apply gate + value live; no restart
```

So a gate flip reaches an online node in ~one MQTT round-trip, and an offline node
picks it up on its next checkin — exactly the "utilize and refresh when changed"
requirement, with no new plumbing.

## Rollout sequence (using the gate)

1. **Ship dark** — `brightness_enabled` default `0`. The agent code, API endpoint, and
   UI all ship, but no node advertises brightness and no slider appears.
2. **Canary one node** — `PUT /kiosks/{id}/meta/settings_overrides {brightness_enabled:1}`.
   Only that kiosk gets `sync_settings`, advertises the capability, and shows the slider.
3. **Fleet on** — `PUT /settings/agent {brightness_enabled:1}`; `_notify_all_nodes`
   flips everyone live.
4. **Tune per node** — set `brightness_default` globally and override per kiosk as needed.

## Scope & limitations (read first)

- **DDC/CI monitors only.** Real backlight luminance over DDC/CI. **TVs on the CEC path
  have no brightness control** — CEC has no luminance command. A TV node simply never
  advertises `brightness`, so the gate + UI stay hidden there regardless.
- **The Raspberry Pi's own HDMI/panel has no software backlight dimming** — dimming
  depends entirely on the external monitor honoring VCP 10.
- **One display per kiosk** — same assumption as resolution; targets the primary DDC
  display.
- **ddcutil writes are slow** (i2c, ~hundreds of ms) — debounce the slider; don't poll.
- VCP brightness persists in the **monitor's NVRAM**, so persistence is best-effort UX,
  not a correctness requirement.

## End-to-end flow (value set)

```
Dashboard ──PUT /kiosks/{id}/brightness {value:0-100}──▶ API
                                                          │  validate 0–100
                                                          │  store NodeMeta(brightness)   (durable, per node)
                                                          │  dispatch MQTT set_brightness
                                                          ▼
                                                     Pi agent  (only acts if gate enabled)
                                                          └─ ddcutil setvcp 10 <value>     (immediate)
                                                          └─ heartbeat back current value
```

## Implementation by layer

### 1. Pi agent — `src/pi-agent/agent.py`

**(a) Consume the gate in `_apply_settings()`** (~line 2411, alongside how
`display_resolution` is consumed today). Store the gate + default on the agent, and
react so the change is live:

```python
self._brightness_enabled = bool(int(s.get("brightness_enabled", 0)))
self._brightness_default = max(0, min(100, int(s.get("brightness_default", 80))))
if self._brightness_enabled:
    # gate on: ensure capability is advertised (if hardware-capable) and apply default
    self._ensure_capability("brightness")
    if self._brightness_default is not None:
        _set_brightness(self._brightness_default)
else:
    # gate off: drop the capability so the dashboard control disappears live
    self._drop_capability("brightness")
```

Tying the gate to the **advertised `features` list** means the existing
capability→features→UI gating (the same path that already hides the input/power
controls on incapable hardware) hides the slider when the gate is off — and the next
heartbeat carries the change so the dashboard updates without a manual refresh. Because
`_apply_settings` runs on boot, on every checkin, and on `sync_settings`, the gate is
honored and refreshed automatically.

**(b) Capability probe** in `detect_capabilities()` (~line 859) — same shape as the
existing probes; this records whether the *hardware* supports VCP 10. The effective
advertised feature is `hardware_supports_brightness AND brightness_enabled`:

```python
# brightness: ddcutil can read/write VCP 10 (luminance)
try:
    r = subprocess.run(["ddcutil", "getvcp", "10"], capture_output=True, text=True, timeout=15)
    detected = r.returncode == 0
    probes["brightness"] = {"cmd": "ddcutil getvcp 10", "returncode": r.returncode,
        "stdout": r.stdout.strip()[:1000], "stderr": r.stderr.strip()[:500], "detected": detected}
    if detected:
        caps.append("brightness")
except Exception as exc:
    probes["brightness"] = {"cmd": "ddcutil getvcp 10", "error": str(exc), "detected": False}
```

**(c) `_set_brightness` / `_get_brightness` helpers** — single-path DDC/CI (no CEC/wlopm
fallback; those have no luminance):

```python
def _set_brightness(value: int) -> bool:
    value = max(0, min(100, int(value)))
    r = subprocess.run(["ddcutil", "setvcp", "10", str(value)], capture_output=True, text=True, timeout=10)
    if r.returncode == 0:
        logger.info("Brightness set to %d via ddcutil VCP 10", value); return True
    logger.warning("Brightness set failed (exit %d): %s", r.returncode, r.stderr.strip()); return False
```

**(d) `set_brightness` command branch** in `handle_command()` (~line 1842, next to
`set_input`). **Gate-checked** — refuse if disabled, as defense in depth even though the
UI hides the control:

```python
elif command == "set_brightness":
    if not (_agent and _agent._brightness_enabled):
        _report_command("set_brightness", False, "Brightness feature disabled for this node", command_id=command_id); return
    value = cmd.get("value")
    if value is None:
        _report_command("set_brightness", False, "Missing value", command_id=command_id); return
    if not _set_brightness(value):
        _report_command("set_brightness", False, "ddcutil setvcp 10 failed", command_id=command_id); return
    _agent._current_brightness = int(value)  # suppress any watcher re-report; optional immediate heartbeat
```

**(e) Heartbeat field (optional).** Add `current_brightness` to the heartbeat payload
(like `current_input` / `display_on`) so the slider tracks the live value. A tight
brightness *watcher* is deliberately **not** added — luminance rarely changes
out-of-band and each `getvcp 10` is a slow i2c read; report on the hourly metadata
checkin plus right after a `set_brightness`.

### 2. API

**Gate + default (per-node) — `settings_service.py` + existing routers.** No new gate
endpoint: the additions to `AGENT_SETTING_DEFAULTS` / `SETTING_BOUNDS` /
`OVERRIDABLE_KEYS` / `NODE_AFFECTING_KEYS` above make the gate settable globally via the
existing `PUT /settings/agent` and per-node via the existing
`PUT /kiosks/{id}/meta/settings_overrides`. Both already fire `sync_settings`. The
`AgentSettingsUpdate` pydantic model in `routers/agent_settings.py` needs the two new
optional fields so the global PUT accepts them.

**Value — `routers/kiosks.py`**, mirroring `set_input` / `set-resolution` (~line 488):

```python
class BrightnessPayload(BaseModel):
    value: int = Field(ge=0, le=100)

@router.put("/{kiosk_id}/brightness", status_code=204)
async def set_brightness(kiosk_id, payload, session=Depends(get_session)):
    kiosk = await kiosk_service.get_by_id(session, kiosk_id)
    if kiosk is None: raise HTTPException(404, "Kiosk not found")
    dispatch_command(session, kiosk_id, command="set_brightness", subject=str(payload.value),
                     payload={"command": "set_brightness", "value": payload.value})
    # persist last value as NodeMeta("brightness") — per node, same upsert as display_resolution
    ...
    await session.commit()
```

Validation (0–100) lives here; the agent clamps again defensively. No change to
`ALLOWED_COMMANDS` (that set is only the generic value-less `/command` route).

### 3. UI — `src/ui/src/...`

- **Settings → Agent Settings** (`AppSettings.vue` / wherever the agent-settings form
  lives): add a **Brightness enabled** toggle and a **Default brightness** field, bound
  to `brightness_enabled` / `brightness_default` (the global defaults). This is where the
  fleet-wide gate is flipped.
- **Per-node override** (`KioskEdit.vue`, alongside the existing per-node setting
  overrides that write `settings_overrides`): allow overriding `brightness_enabled` /
  `brightness_default` for one kiosk — the canary path.
- **The slider** (`KioskDetail.vue`, ~line 107, next to INPUT / DISPLAY POWER): gate on
  the node's advertised feature, which already reflects the live gate state:

```vue
<div v-if="kiosk.features.includes('brightness') && !hiddenControls.has('brightness')">
  <div class="text-xs text-muted">BRIGHTNESS</div>
  <input type="range" min="0" max="100" step="5" v-model.number="liveBrightness"
         :disabled="commandsBlocked" @change="sendBrightness(liveBrightness)" />
  <span class="text-xs">{{ liveBrightness }}%</span>
</div>
```

with `sendBrightness(value)` modelled on `sendInput()` (~line 937), `PUT`ing
`/kiosks/{id}/brightness`. **Debounce on `@change` (release), not `@input` (drag)** —
each write is a slow ddcutil round-trip. `liveBrightness` initializes from the
heartbeat's `current_brightness`, then the stored `NodeMeta`, then `brightness_default`.

Because the slider keys off `kiosk.features.includes('brightness')`, and the agent only
advertises that feature while the gate is enabled, **the gate state drives the UI
automatically** — no separate UI flag lookup needed.

### 4. Setup / capability re-detect

No `setup.sh` change — `ddcutil` is already installed (line 623) and needs no sudo.
After upgrading a node, click **Detect Hardware** once so the `brightness` hardware
capability is probed; the slider then appears once the gate is enabled for that node.

## Files to touch

| File | Change |
|------|--------|
| `src/api/app/services/settings_service.py` | `brightness_enabled` + `brightness_default` in `AGENT_SETTING_DEFAULTS`, `SETTING_BOUNDS`, `OVERRIDABLE_KEYS`, `NODE_AFFECTING_KEYS` |
| `src/api/app/routers/agent_settings.py` | two new optional fields on `AgentSettingsUpdate` |
| `src/api/app/routers/kiosks.py` | `BrightnessPayload` + `PUT /{id}/brightness`; persist `NodeMeta("brightness")` |
| `src/pi-agent/agent.py` | consume gate/default in `_apply_settings`; `brightness` probe; `_set_brightness`/`_get_brightness`; gate-checked `set_brightness` branch; optional `current_brightness` heartbeat + `_ensure/_drop_capability` helpers |
| `src/ui/src/settings/AppSettings.vue` | global gate toggle + default field |
| `src/ui/src/kiosks/KioskEdit.vue` | per-node `brightness_enabled` / `brightness_default` override |
| `src/ui/src/kiosks/KioskDetail.vue` | `brightness`-gated slider + `sendBrightness()` |
| `src/api/alembic/versions/00xx_brightness_settings.py` | optional: seed `brightness_enabled=0` default row |
| `src/api/tests/test_kiosks_router.py`, `test_agent_settings*.py` | endpoint + gate-propagation tests |

## Testing

- **API unit:** `PUT /brightness` rejects <0 / >100 (422), 404 on unknown kiosk,
  dispatches `set_brightness`, upserts per-node `NodeMeta`. Flipping
  `brightness_enabled` globally calls `_notify_all_nodes` (all kiosks get
  `sync_settings`); per-node `settings_overrides` write fires `sync_settings` to **only**
  that kiosk. `effective_settings` merges a per-node `brightness_enabled` override over
  the global default.
- **Agent (real DDC monitor):** with gate **off**, `set_brightness` is refused and
  `brightness` is absent from advertised features; flip gate on via `sync_settings` →
  capability appears and the default applies **without a restart**; `getvcp 10` /
  `setvcp 10` round-trip; gate omitted on a TV / EDID-less phantom.
- **End to end:** dark launch (no slider) → per-node override (slider on one kiosk) →
  global flip (fleet) → drag slider dims the monitor → next heartbeat reflects value →
  reboot retains brightness (NVRAM) and re-reads it.

## Future / nice-to-have

- **Scheduled dimming** (dim overnight) — a server-side cron emitting `set_brightness`,
  reusing this command and gate.
- **Combined "screen-saver" mode** — pair low brightness with `standby` / `display_off`.

## Related

- `docs/dev/display-resolution.md` — the analogous per-node display feature, end to end.
- `docs/dev/feature-flags.md` — why the global UI flag table is *not* used for the gate.
- `docs/research/hdmi-cec.md` — why TVs use CEC (and thus get no brightness).
