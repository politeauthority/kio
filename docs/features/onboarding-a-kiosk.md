# Onboarding a New Kiosk

This doc covers adding a new Raspberry Pi to the kio setup from a fresh OS install through to the node appearing online in the dashboard.

---

## Prerequisites

- Raspberry Pi running Raspberry Pi OS (Wayland/labwc desktop)
- Connected to the local network and reachable via SSH
- SSH hostname configured (e.g. `kio-3`) or IP known
- Display connected via HDMI
- kio API reachable from the Pi (note the URL — setup will ask for it)
- A kiosk created in the kio UI with a node token issued (setup will ask for the token)

Before running setup, SSH into the Pi and update the OS:

```bash
sudo apt-get update && sudo apt-get upgrade -y
```

All other required packages are installed automatically by `setup.sh`.

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

## Step 3 — Add deploy tasks to the Taskfile (optional)

Add tasks to `Taskfile.yaml` modelled on the existing `kio-2`/`kio-3` tasks. They delegate to the shared, variabilized `_kio:*` tasks, so you only set the hostname and which config file to push:

```yaml
  kio-3:setup:
    desc: First-time setup of kio-3 — install with the dev config
    cmds:
      - task: _kio:install
        vars: {HOST: kio-3, CONFIG: configs/agents/kio-3-kiosk.dev.yaml}

  kio-3:deploy:
    desc: Deploy kio-3 — scp local source, run setup.sh (keeps config), restart
    cmds:
      - task: _kio:install
        vars: {HOST: kio-3}

  kio-3:dev:
    desc: Push dev config to kio-3 and restart the agent
    cmds:
      - task: _kio:config
        vars: {HOST: kio-3, CONFIG: configs/agents/kio-3-kiosk.dev.yaml}

  kio-3:prd:
    desc: Push prod config to kio-3 and restart the agent
    cmds:
      - task: _kio:config
        vars: {HOST: kio-3, CONFIG: configs/agents/kio-3-kiosk.prd.yaml}

  kio-3:logs:
    desc: Stream agent logs from kio-3
    cmds:
      - task: _kio:logs
        vars: {HOST: kio-3}
```

`_kio:install` SCPs `src/pi-agent/.` to the node and runs `setup.sh --local` (never pulls from git).

---

## Step 5 — Run setup on the Pi

The simplest path is the Taskfile (after Step 3 and creating `configs/agents/kio-3-kiosk.dev.yaml`):

```bash
task kio-3:setup
```

Or run `setup.sh` on the Pi directly. SSH in, then either copy the `src/pi-agent/` folder over and run it with `--local`, or pull it from GitHub:

```bash
# from copied source (recommended — no internet needed):
cd /path/to/src/pi-agent && sudo bash setup.sh --local --api-url https://<your-api> --token kio_...

# or bootstrap from GitHub (clones the repo, defaults to the main branch):
curl -fsSL https://raw.githubusercontent.com/politeauthority/kio/main/src/pi-agent/setup.sh \
  | sudo bash -s -- --api-url https://<your-api> --token kio_...
```

If you don't pass `--api-url`/`--token`, the script prompts for them (only those two). See [API certificate (TLS) options](#api-certificate-tls-options) below for the cert flag to add (`--accept-cert` is typical for a private cert).

> `--env dev` / `--env prd` is optional: it tags the installed config as that environment (saved on the Pi as `/etc/kio/kiosk.<env>.yaml`) so you can switch between them later with `task <node>:dev` / `task <node>:prd`. It does **not** pre-fill the API URL.

The script installs system packages, writes `/etc/kio/kiosk.yaml`, installs the agent to `/opt/kio-agent/`, enables the systemd service, configures the labwc graphical autostart, and turns on auto-login.

**Reboot to apply all changes:**

```bash
sudo reboot
```

A reboot is required for the HDMI cmdline (`video=HDMI-A-1`), `hdmi_force_hotplug`, and the `i2c` group change (display power / input switching). After reboot the agent starts automatically and begins sending heartbeats — the kiosk should appear **online** in the dashboard within 30 seconds.

---

## API certificate (TLS) options

If your kio API is served over HTTPS, the Pi has to trust the API's certificate before it can talk to it securely. What you do depends on the kind of certificate the API uses:

| Your API's certificate | What to do | Add to the setup command |
|------------------------|-----------|--------------------------|
| Public certificate (Let's Encrypt, etc.) | Nothing — it's trusted automatically | *(nothing)* |
| Private / self-signed certificate | Trust it on first connect and remember it | `--accept-cert` |
| You already have the CA file | Provide it so it's trusted from the start | `--ca-cert /path/to/ca.crt` |
| Plain HTTP, or just testing | Skip the security check | `--insecure-tls` |

Most self-hosted setups use a private certificate — use **`--accept-cert`**. During setup it downloads the API's certificate, saves it on the Pi, and prints a **fingerprint** (a `Leaf SHA-256:` line). Compare that fingerprint against your API's real certificate before continuing — that confirms nothing tampered with the connection. From then on the agent trusts only that exact certificate.

```bash
sudo bash setup.sh --accept-cert --api-url https://your-api.example.local --token kio_...
```

> **"Reachable but its TLS certificate is not trusted"** — if setup stops with this message, it's this step. Re-run with one of the options above.

If you'd rather not have setup download its source from the internet, copy the `src/pi-agent/` folder to the Pi yourself and add `--local` — setup then runs only from those files and never touches git.

---

## Internal API hostnames (custom DNS)

If your API URL is an internal name like `https://api.kio.example.local` (rather than a public domain), the Pi needs a DNS server that knows that name — otherwise setup fails to resolve/reach the API. Point the Pi at a DNS server that can resolve it (for example a **Pi-hole**) with `--dns`:

```bash
sudo bash setup.sh --dns 192.168.50.2 --accept-cert \
  --api-url https://api.kio.example.local --token kio_...
```

- Comma-separate multiple servers: `--dns 192.168.50.2,1.1.1.1`.
- Run with a terminal attached and setup will **prompt** for a custom DNS server (leave blank to keep the Pi's current DNS).
- The setting is applied so it survives reboots.

If your API URL is a plain IP address (e.g. `http://192.168.50.182:8000`), you don't need this.

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
Connected to MQTT at 192.168.50.86:1883   # the mqtt.host from your config
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

Config files live in `configs/agents/` (not committed — they contain node tokens):

| File | Purpose |
|---|---|
| `kio-3-kiosk.dev.yaml` | API URL, token, MQTT settings for dev |
| `kio-3-kiosk.prd.yaml` | API URL, token, MQTT settings for prod |
| `example-config.yaml` | Template to copy when adding a new node |

---

## Troubleshooting

**Agent not starting:**
```bash
task kio-3:logs
```

**Heartbeat failing (token invalid):**
Verify the token in `configs/agents/kio-3-kiosk.dev.yaml` matches what was created in the dashboard. Tokens are shown only once — if lost, revoke it and create a new one.

**MQTT not connecting:**
Check `topic_prefix` in `kio-3-kiosk.dev.yaml` is `kio/dev`. Confirm the broker (the `mqtt.host`/`mqtt.port` in your config) is reachable from the Pi:
```bash
ssh kio-3 "nc -zv <mqtt-host> 1883"
```

**Wrong config active:**
Check what's currently on the Pi:
```bash
ssh kio-3 "cat /etc/kio/kiosk.yaml"
```
Push the correct config with `task kio-3:dev` or `task kio-3:prd`.
