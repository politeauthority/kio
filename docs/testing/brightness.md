# Display Brightness — Test Runbook (kio-2)

How to test the per-node display-brightness feature on kio-2. The feature ships
behind the `brightness_enabled` gate (default off) and drives the monitor's
luminance over DDC/CI (`ddcutil setvcp 10`). Design + architecture live in
`docs/dev/display-brightness.md`.

## 0. Make-or-break: does kio-2's display do DDC/CI brightness?

The whole feature rides on VCP 10. kio-2's panel has been finicky (see
`docs/kio-2-changes.md`), so confirm hardware support **before** touching the stack:

```bash
ssh kio-2 "ddcutil getvcp 10"     # luminance read — must succeed
ssh kio-2 "ddcutil setvcp 10 30"  # should visibly dim the panel
ssh kio-2 "ddcutil setvcp 10 90"  # …and back up
```

- **Both succeed** → proceed; the feature works end to end on this node.
- **`getvcp 10` fails / "DDC communication failed"** → this display has no DDC/CI
  brightness (TV-class panel). The agent correctly won't advertise `brightness`, the
  slider won't appear, and there's nothing to test here — you need a DDC/CI monitor.
  This is the **designed** behavior, not a bug.
- **`setvcp` works but `getvcp` doesn't** (some panels are write-only) → the capability
  probe uses `getvcp`, so it would mis-detect as unsupported. Flag it; the probe would
  need to tolerate write-only displays.

## 1. Server side (API + UI)

kio-2's dev config (`configs/agents/kio-2-kiosk.dev.yaml`) points at API
`http://192.168.50.182:8000`, MQTT topic prefix `kio/dev`. The gate, the
`PUT /kiosks/{id}/brightness` endpoint, and the slider all live server-side, so that
dev API + UI must be running this branch.

```bash
task dev:api            # or however the API at :182:8000 is served
task dev:ui
```

No DB migration is required — brightness uses the existing `app_settings` and
`node_meta` key/value tables, and `get_global_settings` falls back to the defaults
(`brightness_enabled = 0`) for unseeded keys.

## 2. Sync the agent to kio-2

```bash
task kio-2:dev      # scp agent.py + dev config to kio-2, restart kio-agent
task kio-2:logs     # stream `journalctl -fu kio-agent` (keep this open)
```

## 3. Populate the capability

Capabilities re-probe **only** on the explicit **Detect Hardware** button (upgrades
deliberately don't clobber a node's features). In the dashboard: open kio-2 → click
**Detect Hardware**. Confirm `brightness` shows up in the detect log / agent logs.

## 4. Enable the gate (canary kio-2 first)

Start per-node so only kio-2 is affected:

- **Per-node (recommended for the test):** kio-2 **Edit** page → set
  `Brightness enabled (0 = off, 1 = on)` override = `1` → Save. Writes
  `settings_overrides` and fires `sync_settings` to **just kio-2**.
- **Fleet-wide:** Settings → Agents → **Display brightness** = On → Save (fires
  `sync_settings` to every node).

In `task kio-2:logs` you should see the agent **re-pull settings live, without a
restart** — that's the gate-refresh path working:

```
Applied settings from api: ...
Brightness set to 80 via ddcutil VCP 10
```

## 5. Verify

| Check | Expected |
|------|----------|
| Slider appears | kio-2 detail page shows a **BRIGHTNESS** control once the gate is on (gated on the advertised `brightness` feature) |
| Drag the slider (fires on release) | Panel dims; logs show `Brightness set to N via ddcutil VCP 10` |
| Reload the dashboard | Slider returns to the last value (persisted as `meta.brightness`) |
| Per-node default | Setting `brightness_default` (global or per-node) and re-enabling applies that level |
| Gate off | Flip the override back to `0` → slider disappears on next heartbeat; a `set_brightness` is refused: `Brightness feature disabled for this node` |
| Live refresh | Toggling the gate updates the node within ~one MQTT round-trip (no reboot); offline nodes pick it up on the next `settings_checkin_seconds` |

## Fast iteration

- Agent code changed → `task kio-2:dev` (re-sync + restart).
- API/UI changed → redeploy `.182`.
- Isolate hardware from software → `ssh kio-2 "ddcutil setvcp 10 <n>"` bypasses the
  whole stack.

## Troubleshooting

| Symptom | Likely cause |
|--------|--------------|
| No slider after enabling the gate | `brightness` not in the node's features — run **Detect Hardware**; if still absent, `getvcp 10` fails on this display (no DDC/CI brightness) |
| Slider present, drag does nothing | `ddcutil setvcp 10` failing on the node — check `task kio-2:logs` for `Brightness set failed`; test directly with `ssh kio-2 "ddcutil setvcp 10 30"` |
| Gate flip doesn't reach the node | MQTT down — the node still picks it up on the next settings checkin (≤ `settings_checkin_seconds`); confirm `kio/dev` broker at `192.168.50.86:1883` is reachable |
| `set_brightness` refused in logs | Gate is off for this node — enable it globally or via the per-node override |

## Related

- `docs/dev/display-brightness.md` — design & architecture.
- `docs/dev/display-resolution.md` — the analogous per-node display feature.
- `docs/kio-2-changes.md` — kio-2's display history (why VCP support is worth checking).
