# Resolution Settings — Debugging & Fix Log

Resolution changes set from the dashboard did not persist across reboots/restarts
on kio-2, and on a fresh boot the display came up at the monitor's default
(3840x2160@30) instead of the configured mode.

## Root causes & fixes

### 0. Edits initially landed in the wrong clone

There are two clones on this machine:
- `/Users/alix/Programming/repos/kio` (branch `feat/urls-model`)
- `/Users/alix/Programming/repos/kio-next` (branch `feat/resolution`) ← **deploy source**

`task kio-2:deploy` is run from `kio-next`. An earlier round of edits was applied to
`kio`, so the deploy pushed fresh-timestamped files that did **not** contain the new
code. All fixes below are in `kio-next`.

### 1. set_resolution command never reported success

The MQTT `set_resolution` handler only called `_report_command` on failure, so the
command sat "pending" in the UI forever. Added a success report after a successful
apply.

### 2. Resolution not re-applied at boot (kanshi)

The kio-agent systemd unit starts on `network-online.target`, before the labwc
Wayland session exists. At that point `set-resolution`/wlr-randr can't reach a
compositor, so the stored resolution wasn't applied. The 5-min settings checkin
eventually retried, leaving the display wrong for minutes.

Fix: drive [kanshi](https://sr.ht/~emersion/kanshi/), a Wayland output-config daemon,
from the boot path.

> Note: the Pi OS labwc image already launches kanshi from `/etc/xdg/labwc/autostart`,
> so the daemon was always running — with an **empty config**, doing nothing. The real
> missing piece was the config file, which the agent now writes.

- `agent.py`: `_write_kanshi_config()` writes `~/.config/kanshi/config` from the
  `display_resolution` NodeMeta value. Called from both the `set_resolution` handler
  and `_apply_settings`, so the kanshi config always tracks the database.
- `setup.sh`: `apt install kanshi` (guarantee present after a reflash), create
  `~/.config/kanshi/`, and add `pkill -x kanshi; kanshi &` to the labwc autostart.
  The `pkill -x` dedups: labwc runs the system autostart *and* the user autostart, so
  without it two kanshi instances run. The user autostart runs second, so killing first
  leaves exactly one instance — and guarantees kanshi runs even on an image whose base
  autostart doesn't start it.
- kanshi applies the mode when the compositor starts and on every reconnect.

### 2b. Phantom HDMI port → multi-profile config

The Pi's forced-hotplug (`hdmi_force_hotplug`) makes the unused second HDMI port
intermittently appear as a connected output with no EDID — wlr-randr shows it as
`HDMI-A-2 "(null) (null) (HDMI-A-2)"`. kanshi only applies a profile when that profile
accounts for **all** connected outputs, so a lone single-output profile logs
`no profile matched` the moment the phantom appears, and the resolution silently
reverts to the monitor default.

`_write_kanshi_config()` therefore enumerates the live outputs (`_wlr_outputs()`) and
emits two profiles:
```
profile kiosk_dual {                       # matches when the phantom is present
    output "Dell Inc. DELL S2721QS 7W2WZY3" mode 1920x1080@60Hz position 0,0
    output "HDMI-A-2" disable               # phantom turned off
}
profile kiosk_solo {                        # matches when only the real display is up
    output "Dell Inc. DELL S2721QS 7W2WZY3" mode 1920x1080@60Hz position 0,0
}
```
The target display is selected as the sole **real (EDID-bearing)** output, never a
`(null)` phantom — even when the stored connector name (e.g. a stale `HDMI-A-2`)
coincidentally matches the phantom's current connector. Phantom `(null)` make/model/serial
are filtered so phantoms are description-less.

### 2c. kanshi reload + live-apply connector resolution

- kanshi reads its config **only at startup** (no SIGHUP reload, no `kanshictl` on the
  Pi's version — both verified). So after the agent rewrites the config on a running
  session, `_reload_kanshi()` restarts the daemon; otherwise a later reconnect would
  re-apply the stale in-memory profile. It only reloads when the file content actually
  changed (`_write_kanshi_config` returns a changed flag), avoiding churn on every checkin.
- The best-effort live `set-resolution` apply targets `_current_connector(stored)` — the
  real display present now — so it no longer fails with `unknown output HDMI-A-2` when
  NodeMeta holds a stale connector name.

Boot sequence after fix:
```
kio-agent starts → _apply_settings writes ~/.config/kanshi/config
labwc session   → pkill -x kanshi; kanshi & reads the config → applies resolution  ✓ (before Chromium)
```

Validated on kio-2: after a reboot, exactly one kanshi instance runs and the display
comes up at the stored mode (held `800x600@60.317` across reboots in testing) instead
of reverting to `3840x2160@30`.

### 3. Connector names are not stable → key kanshi on the monitor description

wlr-randr enumerated the same physical Dell as `HDMI-A-2` in one boot and `HDMI-A-1`
in another. A kanshi profile (or stored resolution) keyed on the connector name
breaks when the name changes. kanshi can instead match on the stable monitor
description (`make model serial`), which is what the original hand-written
`kio-2-kanshi-config` did: `output "Dell Inc. DELL S2721QS 7W2WZY3" ...`.

Fix: `_wlr_outputs()` resolves each connector to its `Make Model Serial` string via
wlr-randr, and `_write_kanshi_config()` keys the target profile on that description,
falling back to the connector name only when the description can't be resolved (early
boot — rewritten on the next checkin).

### 4. Resolution UI showed every connected output

`_detect_display_modes()` now also parses each output's `Position:` and returns
`(modes, primary_output)` where primary is the output at `0,0`. `collect_hardware_info`
stores `primary_output` in the detect log, and `KioskEdit.vue` filters the resolution
controls to just that output (the kiosk's active display). Falls back to all outputs
for older detect logs.

> After deploying, click **Detect Hardware** once so `primary_output` is recorded.

### 5. Static kanshi config removed

`configs/agents/kio-2-kanshi-config` is deleted — the agent now generates the config
at runtime from NodeMeta, so it generalises to any node without a per-node file.

## Files changed (kio-next)

| File | Change |
|------|--------|
| `src/pi-agent/agent.py` | `_wlr_outputs`, `_current_connector`, `_write_kanshi_config` (multi-profile, returns changed), `_reload_kanshi`; `_detect_display_modes` returns primary output; `collect_hardware_info` stores `primary_output`; kanshi write + reload + current-connector live apply + success report in `set_resolution` and `_apply_settings` |
| `src/pi-agent/setup.sh` | install kanshi; create `~/.config/kanshi`; add `pkill -x kanshi; kanshi &` to labwc autostart (dedup) |
| `src/ui/src/kiosks/KioskEdit.vue` | resolution UI limited to primary output |
| `configs/agents/kio-2-kanshi-config` | deleted (generated at runtime now) |

`set-resolution` wrapper + sudoers entry were already present in kio-next.

## Known limitation

The config is regenerated each settings checkin and on every `set_resolution`. If the
phantom HDMI port appears **mid-session** (between checkins) while the config was written
in a phantom-absent state, kanshi can briefly fail to match until the next checkin
rewrites the config and reloads kanshi (≤ `settings_checkin_seconds`, default 300s). It
self-heals; it is not persistent. Reboots are unaffected — the config is rewritten from
the live output set at boot.

## Deploy & verify

```bash
task kio-2:deploy        # needs sudo password (runs setup.sh: kanshi, autostart)
ssh kio-2 sudo reboot
# then click Detect Hardware in the dashboard to record primary_output
```

Verify on the node:
```bash
cat ~/.config/kanshi/config     # profile keyed on the Dell description
pgrep -a kanshi                 # running, launched from labwc autostart
# display should be at the configured mode, not 3840x2160@30
```
