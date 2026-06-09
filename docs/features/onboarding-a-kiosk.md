# Onboarding a New Kiosk

This doc covers adding a new Raspberry Pi to the kio setup from a fresh OS install through to the node appearing online in the dashboard.

---

## Prerequisites

- Raspberry Pi running Raspberry Pi OS (Wayland/labwc desktop)
- Connected to the local network and reachable via SSH
- SSH hostname configured (e.g. `kio-3`) or IP known
- Display connected via HDMI

### Required system packages

The setup scripts install these automatically, but if running manually:

```bash
sudo apt-get install -y ddcutil v4l-utils
sudo usermod -aG i2c $USER   # lets ddcutil run without sudo (re-login to apply)
```

| Package | Provides | Used for |
|---|---|---|
| `ddcutil` | `ddcutil` | Display power (VCP D6), input switching (VCP 60) |
| `v4l-utils` | `cec-ctl` | CEC standby/wake over HDMI |
| *(pre-installed)* | `wlr-randr`, `wlopm` | Wayland output management |

---

## Step 1 — Create the kiosk in the dashboard

Open the kio dashboard and create the kiosk:

- **Dev:** `http://kio-dev.example.local`
- **Prod:** `http://kio.example.local`

Click **+ Add Kiosk**, fill in:
- **Name** — human-readable label (e.g. `Lobby Display`)
- **Hostname** — the Pi's SSH hostname (e.g. `kio-3`)

Copy the kiosk **UUID** from the dashboard — you'll need it in the config files.

---

## Step 2 — Create node tokens

On the kiosk detail page, open the **Node Tokens** section and create two tokens — one for dev, one for prod. Give each a description so you can tell them apart (`kio-3 dev`, `kio-3 prd`).

Copy each token value when it's displayed — it won't be shown again.

---

## Step 3 — Add node config files to the repo

Node-specific files live in `configs/agents/` and are named with the node prefix so they can all share one directory. Config files containing secrets are gitignored.

### `configs/agents/kio-3-kiosk.dev.yaml`

Gitignored. Fill in the UUID and dev token from steps 1 and 2.

```yaml
id: <uuid from dashboard>
features: []                    # list items: display_power, cec, input_switch

api:
  url: http://kio-dev.example.local
  token: kio_...                # token created in the dev dashboard

mqtt:
  host: 192.168.1.100
  port: 1883
  topic_prefix: kio/dev
```

### `configs/agents/kio-3-kiosk.prd.yaml`

Gitignored. Fill in the UUID and prod token from steps 1 and 2.

```yaml
id: <uuid from dashboard>
features: []                    # list items: display_power, cec, input_switch

api:
  url: https://api.kio.example.local
  token: kio_...                # token created in the prod dashboard
  tls_verify: false

mqtt:
  host: 192.168.1.100
  port: 1883
  topic_prefix: kio/prd
```

### `configs/agents/kio-3-kanshi-config`

Committed. Configures monitor output for this specific display. Find the exact output name by SSHing into the Pi and running:

```bash
WAYLAND_DISPLAY=wayland-0 wlr-randr
```

Then write the kanshi profile:

```
profile kiosk {
    output "Dell Inc. DELL S2721QS XXXXXXX" mode 1920x1080@60Hz position 0,0
}
```

### `configs/agents/kio-3-hosts`

Committed. Appended to `/etc/hosts` on the Pi for local DNS resolution.

```
# KIO-HOSTS
192.168.1.10 kio-dev.example.local kio.example.local api.kio-dev.example.local api.kio.example.local
# END KIO-HOSTS
```

---

## Step 4 — Add deploy tasks to the Taskfile

Add tasks to `Taskfile.yml` modelled on the existing `kio-2` tasks. The deploy task scps agent code and node-specific configs directly to their target locations.

```yaml
  kio-3:deploy:
    desc: Deploy pi-agent to kio-3 and restart the agent service
    cmds:
      - ssh kio-3 "mkdir -p ~/kio/pi-agent"
      - scp -r src/pi-agent/. kio-3:~/kio/pi-agent && scp VERSION kio-3:~/kio/pi-agent/VERSION
      - ssh kio-3 "sudo cp ~/kio/pi-agent/agent.py ~/kio/pi-agent/VERSION /opt/kio-agent/"
      - scp configs/agents/kio-3-kanshi-config kio-3:~/.config/kanshi/config
      - ssh kio-3 "printf 'pkill wf-panel-pi\nunclutter-xfixes --timeout 1 &\n~/kio/pi-agent/scripts/browser-start\n' > ~/.config/labwc/autostart && chmod +x ~/.config/labwc/autostart"
      - scp configs/agents/kio-3-hosts kio-3:/tmp/kio-hosts
      - ssh kio-3 "sudo sed -i '/# KIO-HOSTS/,/# END KIO-HOSTS/d' /etc/hosts && sudo bash -c 'cat /tmp/kio-hosts >> /etc/hosts'"
      - ssh kio-3 "sudo systemctl restart kio-agent"

  kio-3:dev:
    desc: Push dev config to kio-3 and restart the agent
    cmds:
      - scp configs/agents/kio-3-kiosk.dev.yaml kio-3:/etc/kio/kiosk.yaml
      - ssh kio-3 "sudo systemctl restart kio-agent"
      - echo "kio-3 -> dev"

  kio-3:logs:
    desc: Stream agent logs from kio-3
    cmds:
      - ssh kio-3 "sudo journalctl -fu kio-agent"

  kio-3:prd:
    desc: Push prod config to kio-3 and restart the agent
    cmds:
      - scp configs/agents/kio-3-kiosk.prd.yaml kio-3:/etc/kio/kiosk.yaml
      - ssh kio-3 "sudo systemctl restart kio-agent"
      - echo "kio-3 -> prd"

  kio-3:release-prd:
    desc: Deploy current agent files to kio-3 and switch to prod config
    cmds:
      - task: kio-3:deploy
      - task: kio-3:prd
```

---

## Step 5 — Run setup on the Pi

SSH into the Pi, copy the `pi-agent` directory over, and run the setup script:

```bash
ssh kio-3
cd ~/kio/pi-agent
bash setup.sh --env dev --token kio_...
```

The script installs system packages, writes `/etc/kio/kiosk.yaml`, installs the agent to `/opt/kio-agent/`, enables the systemd service, and configures auto-login.

**Reboot to apply all changes** (required for the `i2c` group to take effect):

```bash
sudo reboot
```

After reboot the agent starts automatically and begins sending heartbeats. The kiosk should appear **online** in the dashboard within 30 seconds.

---

## Step 6 — Detect capabilities

Open the kiosk edit page in the dashboard and click **Detect Capabilities**. This sends a command to the agent which probes the hardware and reports back what it finds:

| Capability | Detected by |
|---|---|
| `display_power` | `ddcutil getvcp D6` succeeds (DDC/CI display power control) |
| `cec` | `/dev/cec0` exists and `cec-ctl` is installed |
| `input_switch` | `ddcutil getvcp 60` succeeds (DDC/CI input source switching) |

Detection takes up to 15 seconds. The page polls for the result and automatically updates the features list when the agent reports back. Save the kiosk to persist the detected features — they are also written back to `/etc/kio/kiosk.yaml` on the Pi so they survive a restart.

If no capabilities are detected, check that the `i2c` group change from the reboot took effect (`groups` should include `i2c`) and that the display is connected and on.

---

## Step 8 — Verify

```bash
task kio-3:logs
```

You should see:

```
Connected to MQTT at 192.168.1.100:1883
Sending metadata heartbeat
kio agent running (kiosk_id=...)
```

Check the dashboard — the kiosk should show as **online** with its current URL and device info populated.

---

## Step 9 — Set browser flags (optional)

The kiosk starts with default Chromium flags. To customise them, go to the kiosk detail page in the dashboard and adjust the **Browser Flags** section. Changes take effect after the next reboot.

Default flags applied:
- `--force-dark-mode`
- `--hide-scrollbars`
- `--ignore-certificate-errors`
- `--disable-session-crashed-bubble`
- `--no-first-run`

---

## Node config file reference

| File | Committed | Purpose |
|---|---|---|
| `kio-3-kiosk.dev.yaml` | No | API URL, token, MQTT settings for dev |
| `kio-3-kiosk.prd.yaml` | No | API URL, token, MQTT settings for prod |
| `kio-3-kanshi-config` | Yes | Monitor output profile |
| `kio-3-hosts` | Yes | Local DNS entries injected into `/etc/hosts` |

---

## Troubleshooting

**Agent not starting:**
```bash
task kio-3:logs
```

**Heartbeat failing (token invalid):**
Verify the token in `configs/agents/kio-3-kiosk.dev.yaml` matches what was created in the dashboard. Tokens are shown only once — if lost, revoke it and create a new one.

**MQTT not connecting:**
Check `topic_prefix` in `kio-3-kiosk.dev.yaml` is `kio/dev`. Confirm the broker at `192.168.1.100:1883` is reachable from the Pi:
```bash
ssh kio-3 "nc -zv 192.168.1.100 1883"
```

**Wrong config active:**
Check what's currently on the Pi:
```bash
ssh kio-3 "cat /etc/kio/kiosk.yaml"
```
Push the correct config with `task kio-3:dev` or `task kio-3:prd`.
