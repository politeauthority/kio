# Kiosk Setup Guide

This guide takes a **fresh Raspberry Pi** from unboxed to a fully working kiosk that boots directly into a full-screen Chromium window and automatically runs the kio agent.

- [Raspberry Pi 4](#raspberry-pi-4)
- [Raspberry Pi 3](#raspberry-pi-3)

---

# Raspberry Pi 4

## Prerequisites

- Raspberry Pi 4 (any RAM)
- microSD card (16 GB+)
- Monitor, keyboard (only needed during setup)
- Network connection (Ethernet recommended for first boot)
- The IP address or hostname of your kio server

---

## Step 1 — Flash the OS

1. Download **Raspberry Pi Imager**: https://www.raspberrypi.com/software/
2. Choose OS: **Raspberry Pi OS (64-bit)** — the Desktop version (Bookworm)
3. Before writing, click the **gear icon** and configure:
   - Hostname: e.g. `kiosk-01`
   - Enable SSH (set a password or add your public key)
   - Set your Wi-Fi credentials (or use Ethernet)
   - Set locale/timezone
4. Write to the SD card, insert into the Pi, and power on.

---

## Step 2 — First Boot & Update

SSH in or use keyboard/monitor:

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y chromium-browser unclutter
sudo reboot
```

`unclutter` hides the mouse cursor after a few seconds of inactivity — useful for kiosks.

---

## Step 3 — Enable Desktop Auto-Login

The kiosk needs to boot straight to the desktop without a login prompt.

```bash
sudo raspi-config
```

Navigate to: **System Options → Boot / Auto Login → Desktop Autologin**

Or non-interactively:

```bash
sudo raspi-config nonint do_boot_behaviour B4
```

---

## Step 4 — Configure Chromium to Launch on Boot

Create the autostart directory and add a `.desktop` entry:

```bash
mkdir -p ~/.config/autostart
```

**`~/.config/autostart/chromium-kiosk.desktop`**

```ini
[Desktop Entry]
Type=Application
Name=Chromium Kiosk
Exec=chromium-browser \
  --kiosk \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --disable-features=TranslateUI \
  --remote-debugging-port=9222 \
  about:blank
X-GNOME-Autostart-enabled=true
```

Key flags:
- `--kiosk` — full-screen, no chrome/UI, cannot exit with Escape
- `--remote-debugging-port=9222` — **required** for the kio agent to control the browser via CDP
- `about:blank` — start blank; the agent will navigate to the correct URL on connect

---

## Step 5 — Disable Screensaver & Power Management

Without this, the screen will go blank after 10 minutes.

**`~/.config/autostart/disable-screensaver.desktop`**

```ini
[Desktop Entry]
Type=Application
Name=Disable Screensaver
Exec=xset s off -dpms
X-GNOME-Autostart-enabled=true
```

Or add to `~/.xsessionrc`:

```bash
xset s off
xset -dpms
xset s noblank
```

Optionally hide the mouse cursor automatically:

**`~/.config/autostart/unclutter.desktop`**

```ini
[Desktop Entry]
Type=Application
Name=Hide cursor
Exec=unclutter -idle 1 -root
X-GNOME-Autostart-enabled=true
```

---

## Step 6 — Install the kio Agent

Copy the `pi-agent/` folder contents to the Pi (via `scp` or USB):

```bash
scp -r pi-agent/ pi@kiosk-01.local:~/kio-agent/
```

Then on the Pi:

```bash
cd ~/kio-agent
bash setup.sh <kio-server-ip>
```

Replace `<kio-server-ip>` with the IP or hostname of the machine running the kio server.

The script will:
1. Generate a unique kiosk UUID
2. Write `/etc/kio/kiosk.conf`
3. Install the agent to `/opt/kio-agent/` with a Python venv
4. Configure Chromium autostart (if not already done)
5. Install and enable the `kio-agent` systemd service

**Note the kiosk UUID printed at the end** — you'll need it for Step 8.

---

## Step 7 — Reboot

```bash
sudo reboot
```

After rebooting:
- The Pi should boot directly to the desktop with no login prompt
- Chromium should open full-screen automatically (blank page initially)
- The kio agent should start automatically

---

## Step 8 — Register the Kiosk in the Dashboard

1. Open the kio dashboard in your browser (`http://<kio-server>:8000`)
2. Click **+ Add Kiosk**
3. Enter:
   - **Name**: e.g. `Lobby Display`
   - **Kiosk ID**: the UUID from the setup script output
   - **Hostname**: `kiosk-01.local` (optional, for your reference)
4. Save — the kiosk will appear as **online** within 30 seconds once the agent connects

---

## Step 9 — Verify

On the Pi, check agent logs:

```bash
journalctl -fu kio-agent
```

Expected output:
```
Connected to MQTT broker at 192.168.1.100:1883
Heartbeat published: {"online": true, "hostname": "kiosk-01", "current_url": "about:blank"}
```

From the dashboard, send a **Set URL** command — Chromium on the Pi should navigate immediately.

---

## Troubleshooting

### Chromium doesn't start
- Check the autostart file path: `~/.config/autostart/chromium-kiosk.desktop`
- Ensure the user is set to auto-login (Step 3)
- Try running the Exec line manually in a terminal

### Agent can't reach MQTT broker
- Verify the kio server IP in `/etc/kio/kiosk.conf`
- Check the server is running: `docker compose ps` on the server
- Test connectivity: `nc -zv <server-ip> 1883`

### CDP not responding (agent logs "CDP unreachable")
- Chromium may not have started yet — the service waits for `graphical.target` but sometimes Chromium takes a few extra seconds. The agent retries automatically.
- Verify Chromium is running: `pgrep chromium`
- Verify the debug port: `curl http://localhost:9222/json`

### Screen goes blank / display turns off
- Re-check the screensaver autostart file
- Also try adding to `/etc/xdg/lxsession/LXDE-pi/autostart`:
  ```
  @xset s off
  @xset -dpms
  @xset s noblank
  ```

### Kiosk shows as offline in dashboard despite being on
- Check the MQTT host in `/etc/kio/kiosk.conf` matches the server's actual IP
- If you changed the server IP, update the config and restart: `sudo systemctl restart kio-agent`

---

## Config File Reference

`/etc/kio/kiosk.conf`:

```ini
[kiosk]
id = xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx   ; UUID assigned at setup

[mqtt]
host = 192.168.1.100   ; kio server IP or hostname
port = 1883
```

---

## Agent Service Commands

```bash
sudo systemctl start kio-agent      # start
sudo systemctl stop kio-agent       # stop
sudo systemctl restart kio-agent    # restart
sudo systemctl status kio-agent     # status
journalctl -fu kio-agent            # live logs
```

---

---

# Raspberry Pi 3

The steps are nearly identical to the Pi 4 guide above. This section covers every difference.

## Prerequisites

- Raspberry Pi 3B or 3B+
- microSD card (16 GB+, Class 10 recommended)
- Monitor, keyboard (only needed during setup)
- Network connection (Ethernet strongly recommended — Wi-Fi on Pi 3 can be unreliable under load)
- The IP address or hostname of your kio server

> **Pi 3B vs 3B+**: Both work. The 3B+ has faster Wi-Fi and a slightly faster CPU. Steps are identical for both.

---

## Step 1 — Flash the OS

1. Download **Raspberry Pi Imager**: https://www.raspberrypi.com/software/
2. Choose OS: **Raspberry Pi OS (32-bit)** — the Desktop version (Bookworm)

   > Use **32-bit** for the Pi 3. The 64-bit OS is technically supported on the 3B+ but the 32-bit build is better tested and uses less RAM — important since the Pi 3 only has 1 GB.

3. Click the **gear icon** before writing and configure:
   - Hostname: e.g. `kiosk-01`
   - Enable SSH (password or public key)
   - Wi-Fi credentials (or use Ethernet)
   - Locale / timezone
4. Write to SD card, insert, power on.

---

## Step 2 — First Boot & Update

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y chromium-browser unclutter
sudo reboot
```

> The package is `chromium-browser` on Raspberry Pi OS Bookworm for both Pi 3 and Pi 4.

---

## Step 3 — Enable Desktop Auto-Login

```bash
sudo raspi-config nonint do_boot_behaviour B4
```

Or via the interactive menu: **System Options → Boot / Auto Login → Desktop Autologin**

---

## Step 4 — Configure Chromium to Launch on Boot

```bash
mkdir -p ~/.config/autostart
```

**`~/.config/autostart/chromium-kiosk.desktop`**

```ini
[Desktop Entry]
Type=Application
Name=Chromium Kiosk
Exec=chromium-browser \
  --kiosk \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --disable-features=TranslateUI \
  --remote-debugging-port=9222 \
  --disable-extensions \
  --disable-plugins \
  --no-first-run \
  --disable-default-apps \
  --process-per-site \
  about:blank
X-GNOME-Autostart-enabled=true
```

Pi 3-specific flags (not needed on Pi 4):
- `--disable-extensions` / `--disable-plugins` — fewer background processes, frees RAM
- `--no-first-run` / `--disable-default-apps` — skips first-run UI that can block startup
- `--process-per-site` — instead of a process per tab, shares a process per site — reduces memory usage on the 1 GB RAM budget

`--remote-debugging-port=9222` is still **required** for the kio agent to work.

---

## Step 5 — Disable Screensaver & Power Management

**`~/.config/autostart/disable-screensaver.desktop`**

```ini
[Desktop Entry]
Type=Application
Name=Disable Screensaver
Exec=xset s off -dpms
X-GNOME-Autostart-enabled=true
```

Also add to `/etc/xdg/lxsession/LXDE-pi/autostart` (this file runs before the user session and is more reliable on Pi 3 with LXDE):

```
@xset s off
@xset -dpms
@xset s noblank
```

**`~/.config/autostart/unclutter.desktop`**

```ini
[Desktop Entry]
Type=Application
Name=Hide cursor
Exec=unclutter -idle 1 -root
X-GNOME-Autostart-enabled=true
```

---

## Step 6 — Increase GPU Memory (optional but recommended)

The Pi 3 has a shared memory pool for CPU and GPU. For smooth video/canvas rendering in Chromium, bump the GPU allocation:

```bash
sudo raspi-config
```

**Performance Options → GPU Memory → set to `128`**

Or directly:

```bash
echo "gpu_mem=128" | sudo tee -a /boot/firmware/config.txt
```

> On older Pi OS versions the file is `/boot/config.txt`, not `/boot/firmware/config.txt`.

---

## Step 7 — Install the kio Agent

Copy the agent files to the Pi:

```bash
scp -r pi-agent/ pi@kiosk-01.local:~/kio-agent/
```

Then on the Pi:

```bash
cd ~/kio-agent
bash setup.sh <kio-server-ip>
```

The script generates a UUID, installs the agent to `/opt/kio-agent/`, and enables the systemd service. **Note the UUID printed at the end.**

---

## Step 8 — Reboot

```bash
sudo reboot
```

After rebooting:
- Pi boots to desktop with no login prompt
- Chromium opens full-screen (blank initially)
- kio agent starts automatically

---

## Step 9 — Register & Verify

Same as the Pi 4 steps:

1. Open the kio dashboard at `http://<kio-server>:8000`
2. Add a kiosk with the UUID from the setup script
3. Within 30 seconds the kiosk should show as **online**
4. Send a **Set URL** command — Chromium should navigate

Check agent logs on the Pi:

```bash
journalctl -fu kio-agent
```

---

## Pi 3 Troubleshooting

### Chromium crashes or is very slow
- Pi 3 with 1 GB RAM can struggle with heavy web pages. Make sure `--process-per-site` and `--disable-extensions` flags are set.
- Check free memory: `free -h`. If available RAM is under 200 MB, the page may be too heavy.
- Consider serving a lightweight local page from the kio server rather than a third-party site.

### Display is blank / no desktop on boot
- Pi 3 occasionally needs a forced HDMI output. Add to `/boot/firmware/config.txt`:
  ```
  hdmi_force_hotplug=1
  hdmi_drive=2
  ```
  Then reboot.

### Wi-Fi drops and agent goes offline
- The Pi 3's Wi-Fi can drop under load. Ethernet is strongly recommended for production kiosks.
- If Wi-Fi must be used, disable power management:
  ```bash
  sudo iwconfig wlan0 power off
  ```
  Make it permanent by adding to `/etc/rc.local` before `exit 0`:
  ```bash
  iwconfig wlan0 power off
  ```

### "CDP unreachable" in agent logs
- Chromium takes longer to start on Pi 3 than Pi 4. The agent will retry automatically every 30 seconds via the heartbeat loop.
- If it never connects: `curl http://localhost:9222/json` — if this returns nothing, Chromium either didn't start or the `--remote-debugging-port=9222` flag is missing.

### All other issues
See the [Pi 4 Troubleshooting](#troubleshooting) section — the causes and fixes are the same.
