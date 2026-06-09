# Display Resolution & Persistence

How a kiosk's display resolution is set, stored, and re-applied across reboots,
restarts, and display reconnects.

## Overview

```
Dashboard ──POST /kiosks/{id}/set-resolution──▶ API
                                                 │  stores NodeMeta(display_resolution)
                                                 │  dispatches MQTT set_resolution
                                                 ▼
                                            Pi agent
                                                 ├─ writes ~/.config/kanshi/config   (durable)
                                                 ├─ reloads kanshi if config changed
                                                 └─ live-applies via wlr-randr        (immediate)
```

Two layers cooperate:

- **kanshi** (Wayland output-config daemon) is the **durable** path. It re-applies the
  configured mode every time the compositor starts and on every display reconnect.
- **wlr-randr** (via the `set-resolution` wrapper) is the **immediate** path, so a change
  takes effect on the running session without waiting for a reconnect.

The source of truth is `NodeMeta.display_resolution` (`{output, mode, rate}`) in the
database. The agent regenerates the kanshi config from it on boot and every settings
checkin, so the on-disk config always tracks the database.

## Why kanshi

The kio-agent systemd unit starts on `network-online.target`, **before** the labwc
Wayland session exists. At that point wlr-randr has no compositor to talk to, so a
boot-time apply would fail and the display would sit at the monitor default until the
next checkin. kanshi closes that gap: it runs inside the labwc session and applies the
profile the moment the compositor comes up — before Chromium launches.

> The Pi OS labwc image already launches kanshi from `/etc/xdg/labwc/autostart`, so the
> daemon is always running. The missing piece was historically just the **config file**,
> which the agent now writes.

## Identifying the display — vendor-agnostic

kanshi can match an output by **connector name** (`HDMI-A-1`) or by **monitor
description** (`make model serial`, e.g. `Dell Inc. DELL S2721QS 7W2WZY3`).

Connector names are **not stable** on the Pi — the same physical monitor enumerated as
`HDMI-A-2` on one boot and `HDMI-A-1` on another. So the agent keys the profile on the
EDID-derived description, read live from `wlr-randr` (`_wlr_outputs()`), which survives
connector renames.

This is **not Dell-specific** — `make model serial` comes from whatever the connected
monitor reports over EDID. Any branded monitor with a normal EDID works identically.

**Fallback for displays with missing EDID:** a monitor that reports `(null)`/`Unknown`
make/model/serial is treated as description-less. For a single such display the agent
falls back to keying on the connector name — still functional, but without
rename-robustness. (This same `(null)` filter is what distinguishes the real display
from the Pi's phantom port; see below.)

## The phantom HDMI port

The Pi's forced hotplug (`hdmi_force_hotplug`, set in `setup.sh`) makes the unused HDMI
port intermittently appear as a connected output with no EDID:

```
HDMI-A-2 "(null) (null) (HDMI-A-2)"
```

kanshi only applies a profile when that profile accounts for **all** connected outputs.
A lone single-output profile therefore logs `no profile matched` the instant the phantom
appears, and the resolution silently reverts to the monitor default.

The agent handles this by emitting **two profiles** (`_write_kanshi_config()`):

```
profile kiosk_dual {                    # matches when the phantom is present
    output "Dell Inc. DELL S2721QS 7W2WZY3" mode 1920x1080@60Hz position 0,0
    output "HDMI-A-2" disable            # phantom turned off
}
profile kiosk_solo {                    # matches when only the real display is up
    output "Dell Inc. DELL S2721QS 7W2WZY3" mode 1920x1080@60Hz position 0,0
}
```

- The **target** is the sole real (EDID-bearing) display, never a `(null)` phantom —
  even when the stored connector name coincidentally matches the phantom's current
  connector.
- Every **other** connected output is `disable`d in the dual profile.
- When the phantom is absent at write time, only the solo-equivalent profile is written.

This is also why the design **assumes one intended display per kiosk** — any other real
output would be disabled as if it were a phantom.

## kanshi reload

kanshi reads its config **only at startup**. On this Pi's version, neither `SIGHUP` nor
`kanshictl` triggers a reload (both verified). So after the agent rewrites the config on
a running session, `_reload_kanshi()` restarts the daemon — otherwise a later reconnect
would re-apply the stale in-memory profile. It reloads only when the file content
actually changed (`_write_kanshi_config()` returns a changed flag), avoiding churn on
every checkin.

## Live apply & stale connectors

The immediate apply goes through `sudo /opt/kio-agent/set-resolution OUTPUT MODE [RATE]`
(a wrapper that handles wlr-randr 0.4's combined `MODE@RATE` format and locates the
Wayland socket). The agent passes `_current_connector(stored)` — the real display present
*now* — instead of the raw stored name, so it doesn't fail with `unknown output HDMI-A-2`
when NodeMeta holds a stale connector.

## Resolution UI (dashboard)

`_detect_display_modes()` returns `(modes, primary_output)`, where `primary_output` is the
output at position `0,0`. `collect_hardware_info()` stores it in the detect log, and
`KioskEdit.vue` limits the resolution controls to that output — so you can't accidentally
target the phantom or a non-kiosk display. Click **Detect Hardware** once after upgrading
a node so `primary_output` is recorded (older detect logs fall back to showing all
outputs).

## Key code

| Symbol | File | Role |
|--------|------|------|
| `_wlr_outputs()` | `src/pi-agent/agent.py` | Parse `[(connector, 'make model serial' \| None)]` from wlr-randr |
| `_write_kanshi_config()` | `src/pi-agent/agent.py` | Emit dual/solo profiles from NodeMeta; returns changed flag |
| `_reload_kanshi()` | `src/pi-agent/agent.py` | Restart kanshi to apply a changed config |
| `_current_connector()` | `src/pi-agent/agent.py` | Resolve a stale stored name to the live real display |
| `_detect_display_modes()` | `src/pi-agent/agent.py` | Modes + `primary_output` for the detect log |
| `set_resolution` handler | `src/pi-agent/agent.py` | MQTT command: write config, reload, live apply, report |
| `_apply_settings()` | `src/pi-agent/agent.py` | Boot/checkin: re-sync kanshi config from NodeMeta |
| `set-resolution` | `src/pi-agent/scripts/set-resolution` | sudo wrapper around wlr-randr |
| autostart + sudoers | `src/pi-agent/setup.sh` | Install kanshi, `pkill -x kanshi; kanshi &`, sudoers entry |

## Boot sequence

```
kio-agent starts → _apply_settings() writes ~/.config/kanshi/config from NodeMeta
labwc session    → pkill -x kanshi; kanshi & → reads config → applies mode  ✓ (before Chromium)
```

The `pkill -x kanshi` in the user autostart dedups against the base image's
`/etc/xdg/labwc/autostart` (labwc runs both), leaving exactly one instance and
guaranteeing kanshi runs even on an image whose base autostart doesn't start it.

## Known limitation

If the phantom port appears **mid-session** (between checkins) while the config was
written in a phantom-absent state, kanshi can briefly fail to match until the next
settings checkin rewrites the config and reloads kanshi (≤ `settings_checkin_seconds`,
default 300s). It self-heals and does not survive as a persistent fault. Reboots are
unaffected — the config is regenerated from the live output set at boot.

## Related

- `docs/testing/resolution.md` — the debugging log and root-cause history behind this design.
