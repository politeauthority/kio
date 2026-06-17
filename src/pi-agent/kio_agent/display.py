"""Display control: power, brightness, resolution, and Wayland/CEC/DDC plumbing.

Spans the several mechanisms a kio node may use to drive its panel — Wayland
compositor (wlopm/wlr-randr/kanshi), HDMI-CEC (cec-ctl), and DDC/CI (ddcutil) —
plus helpers to discover the running Wayland session and the connected outputs.
All functions degrade gracefully when a given mechanism is unavailable.
"""

import glob
import os
import subprocess
import time

from kio_agent.constants import logger

# DDC/CI input-source VCP 60 values, keyed by friendly input name.
INPUT_MAP = {
    "dp1": "0x0f",
    "dp2": "0x10",
    "hdmi1": "0x11",
    "hdmi2": "0x12",
}


def _cec_phys_addr() -> str:
    """This adapter's CEC physical address (e.g. '4.0.0.0'), or '' if unallocated."""
    try:
        r = subprocess.run(
            ["sudo", "cec-ctl", "-d", "/dev/cec0", "--playback"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        for line in r.stdout.splitlines():
            if "Physical Address" in line and "f.f.f.f" not in line:
                return line.split(":", 1)[1].strip()
    except Exception as exc:
        logger.debug("cec phys addr read failed: %s", exc)
    return ""


def _cec_power(on: bool) -> bool:
    """Control display power over HDMI CEC. Returns True if the command was sent.

    Used as the power path for displays that don't support DDC/CI (e.g. Samsung
    TVs), and for explicit wake/standby commands. on -> one-touch-play (wake the
    TV and announce ourselves as active source); off -> standby the TV.
    """
    if not os.path.exists("/dev/cec0"):
        return False
    if on:
        r = subprocess.run(
            ["sudo", "cec-ctl", "-d", "/dev/cec0", "--playback", "-t", "0", "--image-view-on"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        addr = _cec_phys_addr()
        if addr:
            subprocess.run(
                ["sudo", "cec-ctl", "-d", "/dev/cec0", "--playback", "--active-source", f"phys-addr={addr}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        return r.returncode == 0
    r = subprocess.run(
        ["sudo", "cec-ctl", "-d", "/dev/cec0", "--playback", "-t", "0", "--standby"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return r.returncode == 0


def _wayland_env() -> dict | None:
    """Return env vars needed to talk to the running Wayland compositor, or None."""
    sockets = glob.glob("/run/user/*/wayland-0")
    if not sockets:
        return None
    uid = sockets[0].split("/")[3]
    return {**os.environ, "XDG_RUNTIME_DIR": f"/run/user/{uid}", "WAYLAND_DISPLAY": "wayland-0"}


def _wlr_outputs() -> list[tuple[str, str | None]]:
    """Return [(connector, 'make model serial' | None), ...] for every output
    wlr-randr reports. A None description marks a phantom/no-EDID port (the Pi's
    forced-hotplug second HDMI shows up as '(null)'). Empty list if Wayland is
    not up. Order matches wlr-randr output."""
    env = _wayland_env()
    if env is None:
        return []
    try:
        r = subprocess.run(["wlr-randr"], capture_output=True, text=True, timeout=10, env=env)
    except Exception:
        return []
    if r.returncode != 0:
        return []
    outputs: list[tuple[str, str | None]] = []
    current: str | None = None
    fields: dict = {}

    def _flush():
        if current is None:
            return
        parts = [fields.get(k) for k in ("make", "model", "serial")]
        # A phantom/no-EDID port reports its make/model/serial as literally "(null)";
        # treat those (and "Unknown") as absent so it is description-less.
        parts = [p for p in parts if p and p not in ("Unknown", "(null)")]
        outputs.append((current, " ".join(parts) if parts else None))

    for line in r.stdout.splitlines():
        if line and not line[0].isspace():
            _flush()
            current = line.split()[0]
            fields = {}
        elif current:
            s = line.strip()
            for key, label in (("make", "Make:"), ("model", "Model:"), ("serial", "Serial:")):
                if s.startswith(label):
                    fields[key] = s.split(":", 1)[1].strip()
    _flush()
    return outputs


def _current_connector(stored: str) -> str:
    """Resolve a (possibly stale) stored connector name to the real display present
    now. Prefers a real (EDID-bearing) display over raw connector presence, because
    the Pi's phantom port can occupy the stored name (e.g. HDMI-A-2) while the actual
    monitor is on another connector."""
    outs = _wlr_outputs()
    real = [c for c, desc in outs if desc]
    if stored in real:
        return stored
    if len(real) == 1:
        return real[0]
    names = [c for c, _ in outs]
    return stored if stored in names else (real[0] if real else stored)


def _write_kanshi_config(output: str, mode: str, rate: float | None) -> bool:
    """Write kanshi profiles so the compositor re-applies the resolution on session
    start and every display reconnect. Returns True if the file content changed.

    Generates two profiles because kanshi only matches a profile when it accounts
    for ALL connected outputs, and the Pi exposes a phantom second HDMI port (forced
    hotplug, no EDID) that comes and goes:
      - kiosk_dual: target display at the mode + every other connected output disabled
      - kiosk_solo: target display only (matches when the phantom is absent)
    The target is keyed on its stable make/model/serial description so it survives
    connector renames; phantom ports are referenced by connector name.
    """
    config_dir = os.path.expanduser("~/.config/kanshi")
    os.makedirs(config_dir, exist_ok=True)
    config_path = os.path.join(config_dir, "config")

    outs = _wlr_outputs()
    descriptions = {c: d for c, d in outs if d}
    # Resolve the target connector: prefer the stored name, else the sole real display.
    if output in descriptions:
        target_conn = output
    elif len(descriptions) == 1:
        target_conn = next(iter(descriptions))
    else:
        target_conn = output
    target_id = descriptions.get(target_conn, target_conn)

    rate_str = f"@{rate:g}Hz" if rate is not None else ""
    target_line = f'    output "{target_id}" mode {mode}{rate_str} position 0,0'
    others = [c for c, _ in outs if c != target_conn]

    dual = "\n".join([target_line] + [f'    output "{c}" disable' for c in others])
    blocks = [f"profile kiosk_dual {{\n{dual}\n}}"]
    if others:
        blocks.append(f"profile kiosk_solo {{\n{target_line}\n}}")
    content = "\n".join(blocks) + "\n"

    try:
        if open(config_path).read() == content:
            return False
    except Exception:
        pass
    with open(config_path, "w") as fh:
        fh.write(content)
    logger.info("Wrote kanshi config: target=%r mode=%s%s disabled=%s", target_id, mode, rate_str, others)
    return True


def _reload_kanshi() -> None:
    """Restart kanshi so a config change takes effect immediately. kanshi reads its
    config only at startup (no SIGHUP reload, no kanshictl on the Pi), so without a
    restart a later display reconnect would re-apply the stale in-memory profile.
    No-op when Wayland is not up — kanshi reads the fresh config when it next starts."""
    env = _wayland_env()
    if env is None:
        return
    try:
        subprocess.run(["pkill", "-x", "kanshi"], capture_output=True, timeout=5)
    except Exception:
        pass
    try:
        subprocess.Popen(
            ["kanshi"],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        logger.info("kanshi restarted to apply updated config")
    except FileNotFoundError:
        logger.debug("kanshi not installed — skipping reload")
    except Exception as exc:
        logger.warning("Failed to restart kanshi: %s", exc)


def _restart_browser() -> None:
    """Kill Chromium (if running) and relaunch via browser-start with the Wayland env.

    Called after the browser-flags file changes so the new flags take effect
    without waiting for the next reboot.
    """
    env = _wayland_env()
    if not env:
        logger.warning("_restart_browser: no Wayland session — cannot relaunch Chromium")
        return
    running = subprocess.run(["pgrep", "-f", "chromium.*--kiosk"], capture_output=True)
    if running.returncode == 0:
        subprocess.run(["pkill", "-f", "chromium.*--kiosk"], check=False)
        time.sleep(1)
    subprocess.Popen(["/opt/kio-agent/browser-start"], env=env)
    logger.info("Browser relaunched with updated flags")


def _wlopm_outputs() -> list[str]:
    """Return output names known to the Wayland compositor via wlopm."""
    env = _wayland_env()
    if env is None or not os.path.exists("/usr/bin/wlopm"):
        return []
    try:
        r = subprocess.run(["wlopm"], capture_output=True, text=True, timeout=5, env=env)
        return [line.split()[0] for line in r.stdout.strip().splitlines() if line.strip()]
    except Exception:
        return []


def _detect_display_modes() -> tuple[dict, str | None]:
    """Return (modes_per_output, primary_output_name).

    Tries wlr-randr first (gives modes + refresh rates + position). Falls back to
    DRM sysfs (/sys/class/drm/card*-*/modes) when wlr-randr is not installed or
    the Wayland session is not yet running (e.g. early boot).

    modes is like {"HDMI-A-1": [{"mode": "1920x1080", "rate": 60.0, "current": True}, ...]}.
    primary_output is the output at position 0,0, falling back to the first output.
    """
    import re

    env = _wayland_env()
    if env is not None:
        try:
            r = subprocess.run(["wlr-randr"], capture_output=True, text=True, timeout=10, env=env)
            if r.returncode == 0 and r.stdout.strip():
                modes: dict = {}
                positions: dict = {}
                current_output: str | None = None
                for line in r.stdout.splitlines():
                    if line and not line[0].isspace():
                        current_output = line.split()[0]
                        modes[current_output] = []
                        positions[current_output] = None
                    elif current_output and line.strip():
                        # wlr-randr format: "    1920x1080 px, 60.000000 Hz (current)"
                        m = re.match(r"\s+(\d+x\d+)\s+px,\s+([\d.]+)\s+Hz(.*)", line)
                        if m:
                            mode_str, rate_str, flags = m.group(1), m.group(2), m.group(3)
                            modes[current_output].append(
                                {
                                    "mode": mode_str,
                                    "rate": round(float(rate_str), 3),
                                    "current": "current" in flags,
                                    "preferred": "preferred" in flags,
                                }
                            )
                        else:
                            pm = re.match(r"\s+Position:\s*(\d+),\s*(\d+)", line)
                            if pm:
                                positions[current_output] = [int(pm.group(1)), int(pm.group(2))]
                result = {k: v for k, v in modes.items() if v}
                if result:
                    primary = next(
                        (out for out, pos in positions.items() if pos == [0, 0] and out in result),
                        next(iter(result)),
                    )
                    return result, primary
        except Exception:
            pass

    # DRM sysfs fallback — no refresh rates, but always available
    sysfs_modes: dict = {}
    for modes_path in sorted(glob.glob("/sys/class/drm/card*-*/modes")):
        try:
            output_dir = os.path.dirname(modes_path)
            status_path = os.path.join(output_dir, "status")
            try:
                status = open(status_path).read().strip()
                if status != "connected":
                    continue
            except Exception:
                pass
            # Strip "card*-" prefix so names match wlr-randr output names (e.g. HDMI-A-1)
            output_name = re.sub(r"^card\d+-", "", os.path.basename(output_dir))
            lines = open(modes_path).read().strip().splitlines()
            seen: set[str] = set()
            entry_list = []
            for line in lines:
                mode_str = line.strip()
                if mode_str and mode_str not in seen:
                    seen.add(mode_str)
                    entry_list.append({"mode": mode_str, "rate": None, "current": False, "preferred": False})
            if entry_list:
                sysfs_modes[output_name] = entry_list
        except Exception:
            pass
    primary = next(iter(sysfs_modes)) if sysfs_modes else None
    return sysfs_modes, primary


def _wayland_display_power(on: bool) -> bool:
    """Control display power via Wayland compositor (wlopm). Returns True on success.

    Preferred over DDC for Wayland/labwc setups because it uses compositor DPMS,
    putting the monitor in soft standby that wakes automatically when signal
    resumes — unlike DDC D6=4 which requires a physical button press to exit.
    """
    env = _wayland_env()
    outputs = _wlopm_outputs()
    if not env or not outputs:
        return False
    cmd = "--on" if on else "--off"
    ok = False
    for output in outputs:
        r = subprocess.run(["wlopm", cmd, output], capture_output=True, text=True, timeout=5, env=env)
        if r.returncode == 0:
            ok = True
    return ok


def _set_display_power(on: bool) -> None:
    """Control display power via Wayland + CEC in parallel, with DDC as fallback.

    wlopm handles DPMS signal for monitors (Dell etc) — lets them wake without a
    physical button. CEC handles TV power directly (Samsung etc). Both run when
    available so a Pi connected to a TV gets CEC power control even if wlopm also
    succeeds on the compositor side.
    """
    any_ok = False

    if _wayland_display_power(on):
        logger.info("Display %s via Wayland (wlopm)", "on" if on else "off")
        any_ok = True

    if os.path.exists("/dev/cec0"):
        if _cec_power(on):
            logger.info("Display %s via CEC", "on" if on else "off")
            any_ok = True

    if any_ok:
        return

    # DDC fallback: use D6=2 (standby) not D6=4 (off), so the monitor can wake
    # from video signal without needing a physical button press.
    value = "1" if on else "2"
    result = subprocess.run(
        ["ddcutil", "setvcp", "D6", value],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode == 0:
        logger.info("Display %s via ddcutil VCP D6=%s", "on" if on else "off", value)
    else:
        logger.warning("Display %s failed: wlopm, CEC, and ddcutil all failed", "on" if on else "off")


def _set_brightness(value: int) -> bool:
    """Set display luminance via DDC/CI VCP 10 (0-100). Returns True on success.

    DDC/CI only — unlike power there is no CEC/wlopm fallback, because neither has
    a luminance command. A node whose display lacks DDC/CI never advertises the
    brightness capability, so this is reached only on capable hardware.
    """
    value = max(0, min(100, int(value)))
    r = subprocess.run(
        ["ddcutil", "setvcp", "10", str(value)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if r.returncode == 0:
        logger.info("Brightness set to %d via ddcutil VCP 10", value)
        return True
    logger.warning("Brightness set failed (exit %d): %s", r.returncode, r.stderr.strip())
    return False
