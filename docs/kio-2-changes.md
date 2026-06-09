# kio-2 Change Log

## 2026-06-02

### Fix display flickering — attempt 1 (`/boot/firmware/config.txt`)

Added `hdmi_force_hotplug=1`, `hdmi_group=2`, `hdmi_mode=82` to `config.txt`.

**Ineffective** — the Pi is using the KMS driver (`dtoverlay=vc4-kms-v3d`), which ignores legacy firmware `hdmi_group`/`hdmi_mode` settings. These were reverted.

---

### Fix display flickering — attempt 2 (`/boot/firmware/cmdline.txt` + `config.txt`)

**Root cause:** Pi was outputting 4K (3840x2160) @ 30Hz. Most monitors flicker or struggle at 30Hz. The `hdmi_group`/`hdmi_mode` config.txt settings do not apply when the KMS driver is active.

**Fix:**

`/boot/firmware/cmdline.txt` — appended:
```
video=HDMI-A-1:1920x1080@60
```
This forces 1920x1080 @ 60Hz at the kernel level, which works with the KMS driver.

`/boot/firmware/config.txt` — removed non-functional `hdmi_group=2` and `hdmi_mode=82`, kept:
```
hdmi_force_hotplug=1
```

**Ineffective** — `video=HDMI-A-1:1920x1080@60` was ignored because the display only reports ~30Hz modes; kernel silently falls back to default (4K@30Hz). Additionally, xrandr cannot shrink the virtual framebuffer at runtime once X has started at 4K.

---

### Fix display flickering — attempt 3 (`/etc/X11/xorg.conf.d/10-monitor.conf` + `cmdline.txt`)

**Root cause of previous attempt failing:** All available modes on HDMI-A-1 are capped at ~30Hz, so `@60` silently failed. The virtual screen size is also fixed at X startup — xrandr cannot downscale from 4K to 1080p at runtime.

**Fix:**

Created `/etc/X11/xorg.conf.d/10-monitor.conf` — forces the X server to start with a 1920x1080 virtual screen:
```
Section "Monitor"
  Identifier "HDMI-A-1"
  Option "PreferredMode" "1920x1080"
EndSection

Section "Screen"
  Identifier "Screen0"
  Monitor "HDMI-A-1"
  DefaultDepth 24
  SubSection "Display"
    Depth 24
    Modes "1920x1080"
    Virtual 1920 1080
  EndSubSection
EndSection
```

Updated `/boot/firmware/cmdline.txt` — changed `@60` to `@30` to match available modes:
```
video=HDMI-A-1:1920x1080@30
```

**Requires reboot to take effect.**

---

### Add local DNS entry for Grafana (`/etc/hosts` + cloud-init template)

Added `192.168.1.80 grafana.example.local` to `/etc/hosts` for immediate effect, and to `/etc/cloud/templates/hosts.debian.tmpl` to survive reboots (cloud-init regenerates `/etc/hosts` from this template on boot).
