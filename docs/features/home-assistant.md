# Home Assistant Integration

The kio Home Assistant integration exposes every registered kiosk as a HA Device, giving you real-time status, display control, and command buttons directly inside Home Assistant.

---

## What gets exposed

Each kiosk in kio becomes a single Device in HA. The entities created depend on what hardware capabilities the agent has reported via **Detect Capabilities**.

| Entity | Type | Notes |
|---|---|---|
| Online | Binary sensor | Connectivity class — true when `status == "online"` |
| Current URL | Sensor | The URL currently displayed in Chromium |
| Last Seen | Sensor | Timestamp of the last heartbeat received |
| Agent Version | Sensor | Disabled by default |
| IP Address | Sensor | Disabled by default |
| Reload Page | Button | Refreshes the current browser tab |
| Reboot | Button | Reboots the Pi |
| Detect Capabilities | Button | Triggers a hardware capability scan |
| Standby (CEC) | Button | Sends CEC standby signal — requires `cec` capability |
| Wake (CEC) | Button | Sends CEC wake signal — requires `cec` capability |
| Display Power | Switch | Turns the display on/off — requires `display_power` capability |
| Display Input | Select | Switches between hdmi1/hdmi2/dp1/dp2 — requires `input_switch` capability |

Feature-gated entities only appear after the kiosk agent reports that capability. If you expect a switch or select that isn't showing up, press **Detect Capabilities** on the kiosk in the kio dashboard and wait for the scan to complete.

Kiosks added to kio after the integration was loaded appear automatically within one poll cycle (30 seconds). Kiosks removed from kio are removed from HA within the same window.

---

## Setup

The integration ships as a custom component installed on your HA host. Once installed:

1. **Settings → Devices & Services → Add Integration**
2. Search for **kio**
3. Enter the API URL (e.g. `http://api.kio.example.local`) and optionally an API key
4. Submit — HA validates the connection by calling `GET /kiosks`

All registered kiosks appear immediately as Devices under the integration.

---

## Example automations

**Turn all displays off at night:**
```yaml
automation:
  trigger:
    platform: time
    at: "22:00:00"
  action:
    service: switch.turn_off
    target:
      entity_id:
        - switch.lobby_display_display_power
        - switch.reception_display_power
```

**Alert when a kiosk goes offline:**
```yaml
automation:
  trigger:
    platform: state
    entity_id: binary_sensor.lobby_display_online
    to: "off"
    for: "00:02:00"
  action:
    service: notify.mobile_app
    data:
      message: "Lobby Display has been offline for 2 minutes"
```

**Navigate all kiosks to a dashboard URL on demand:**
```yaml
script:
  kiosks_show_dashboard:
    sequence:
      - service: button.press
        target:
          entity_id: button.lobby_display_reload_page
```

**Wake displays at sunrise:**
```yaml
automation:
  trigger:
    platform: sun
    event: sunrise
  action:
    service: switch.turn_on
    target:
      entity_id: switch.lobby_display_display_power
```
