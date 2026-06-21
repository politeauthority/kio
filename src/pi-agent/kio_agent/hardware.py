"""Hardware capability probing and inventory collection.

Probes DDC/CI VCP features and HDMI-CEC to decide which display-control
capabilities a node has, and gathers a detailed hardware inventory (OS, CPU/board,
RAM, storage, temperature, display, CEC bus) for the dashboard. Probes
distinguish a definitive 'unsupported' from a transient 'unknown' so a flaky i2c
read never wipes a working capability.
"""

import os
import subprocess
import time

from kio_agent.constants import _KNOWN_VCP_CAPS, logger
from kio_agent.display import _detect_display_modes


def _classify_ddc_failure(stdout: str, stderr: str) -> str:
    """Classify a non-zero `ddcutil getvcp`: a definitive 'unsupported' (the device
    answered that the feature/display isn't there) vs an 'unknown' (i2c/comm error,
    timeout — the result is undetermined). The distinction matters because an
    'unknown' must never drop a capability the node already had (transient flakiness),
    whereas 'unsupported' legitimately removes it."""
    blob = (stdout + " " + stderr).lower()
    if any(s in blob for s in ("not supported", "feature not found", "invalid vcp", "unsupported")):
        return "unsupported"
    return "unknown"


def _probe_vcp(code: str, attempts: int = 3) -> tuple[str, dict]:
    """Probe a ddcutil VCP code, retrying transient failures. Returns (status, info)
    where status is 'supported' | 'unsupported' | 'unknown'. Retries exist because a
    single i2c hiccup during a multi-probe detect would otherwise misreport a working
    capability as absent."""
    info: dict = {"cmd": f"ddcutil getvcp {code}"}
    for attempt in range(1, attempts + 1):
        try:
            r = subprocess.run(["ddcutil", "getvcp", code], capture_output=True, text=True, timeout=15)
            info = {
                "cmd": f"ddcutil getvcp {code}",
                "returncode": r.returncode,
                "stdout": r.stdout.strip()[:1000],
                "stderr": r.stderr.strip()[:500],
                "attempts": attempt,
            }
            if r.returncode == 0:
                return "supported", info
            if _classify_ddc_failure(r.stdout, r.stderr) == "unsupported":
                return "unsupported", info
            # otherwise an unknown/comm failure — retry
        except Exception as exc:
            info = {"cmd": f"ddcutil getvcp {code}", "error": str(exc), "attempts": attempt}
        if attempt < attempts:
            time.sleep(0.5)
    return "unknown", info


def _probe_cec(attempts: int = 3) -> tuple[str, dict]:
    """Probe HDMI-CEC. 'supported' = adapter present and a CEC display is on the bus;
    'unsupported' = no adapter, or the bus reports no display (physical addr f.f.f.f);
    'unknown' = the cec-ctl call errored (retried)."""
    cec_cmd = ["sudo", "cec-ctl", "-d", "/dev/cec0", "--playback", "-S"]
    if not os.path.exists("/dev/cec0"):
        return "unsupported", {"cmd": " ".join(cec_cmd), "error": "/dev/cec0 not found"}
    info: dict = {"cmd": " ".join(cec_cmd)}
    for attempt in range(1, attempts + 1):
        try:
            r = subprocess.run(cec_cmd, capture_output=True, text=True, timeout=10)
            physical = next(
                (line.split(":", 1)[1].strip() for line in r.stdout.splitlines() if "Physical Address" in line),
                "unknown",
            )
            info = {
                "cmd": " ".join(cec_cmd),
                "returncode": r.returncode,
                "stdout": r.stdout.strip()[:1000],
                "stderr": r.stderr.strip()[:500],
                "physical_address": physical,
                "attempts": attempt,
            }
            if r.returncode == 0:
                return ("supported" if physical != "f.f.f.f" else "unsupported"), info
        except Exception as exc:
            info = {"cmd": " ".join(cec_cmd), "error": str(exc), "attempts": attempt}
        if attempt < attempts:
            time.sleep(0.5)
    return "unknown", info


def detect_capabilities() -> tuple[list[str], dict]:
    """Probe hardware and return (capabilities, probes).

    `capabilities` is the list of features probed as 'supported'. `probes` carries
    per-capability debug info plus an explicit `status` (supported/unsupported/unknown)
    and `detected` flag — surfaced in the dashboard so an operator can see what each
    node supports, not just which features happen to be on. The non-destructive merge
    against the unknown status lives in _run_capability_detection."""
    caps: list[str] = []
    probes: dict = {}

    for cap, code in _KNOWN_VCP_CAPS:
        status, info = _probe_vcp(code)
        probes[cap] = {**info, "status": status, "detected": status == "supported"}
        if status == "supported":
            caps.append(cap)

    cec_status, cec_info = _probe_cec()
    probes["cec"] = {**cec_info, "status": cec_status, "detected": cec_status == "supported"}
    if cec_status == "supported":
        caps.append("cec")

    logger.info("Detected capabilities: %s", {k: v["status"] for k, v in probes.items()})
    return caps, probes


def collect_hardware_info() -> dict:
    """Gather detailed hardware information about this node."""
    info: dict = {}

    # OS
    try:
        info["kernel"] = subprocess.run(["uname", "-r"], capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        pass
    try:
        os_fields = {}
        with open("/etc/os-release") as f:
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    os_fields[k] = v.strip('"')
        info["os"] = os_fields.get("PRETTY_NAME", "")
    except Exception:
        pass

    # CPU / board (Pi-specific fields in /proc/cpuinfo)
    try:
        cpuinfo = open("/proc/cpuinfo").read()
        for label, key in [("Model", "board_model"), ("Hardware", "cpu_hardware"), ("Revision", "board_revision")]:
            val = next(
                (line.split(":", 1)[1].strip() for line in cpuinfo.splitlines() if line.startswith(f"{label}\t")), None
            )
            if val:
                info[key] = val
        info["cpu_cores"] = cpuinfo.count("processor\t:")
    except Exception:
        pass

    # RAM
    try:
        meminfo = {}
        for line in open("/proc/meminfo"):
            k, v = line.split(":", 1)
            meminfo[k.strip()] = v.strip()
        total_kb = int(meminfo.get("MemTotal", "0 kB").split()[0])
        info["ram_mb"] = round(total_kb / 1024)
    except Exception:
        pass

    # Storage
    try:
        r = subprocess.run(["df", "-h", "/"], capture_output=True, text=True, timeout=5)
        parts = r.stdout.strip().splitlines()[1].split()
        info["storage"] = {"total": parts[1], "used": parts[2], "free": parts[3], "use_pct": parts[4]}
    except Exception:
        pass

    # Pi temperature and GPU memory
    for vcmd, key in [("measure_temp", "cpu_temp"), ("get_mem gpu", "gpu_mem_mb")]:
        try:
            r = subprocess.run(["vcgencmd"] + vcmd.split(), capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                val = r.stdout.strip()
                if key == "cpu_temp":
                    info[key] = val.replace("temp=", "")
                else:
                    info[key] = int("".join(filter(str.isdigit, val.split("=")[-1])))
        except Exception:
            pass

    # Display info via ddcutil detect
    try:
        r = subprocess.run(["ddcutil", "detect"], capture_output=True, text=True, timeout=20)
        if r.returncode == 0 and r.stdout.strip():
            display: dict = {}
            for line in r.stdout.splitlines():
                line = line.strip()
                for field, dkey in [
                    ("Manufacturer:", "manufacturer"),
                    ("Model:", "model"),
                    ("Serial number:", "serial"),
                    ("Product code:", "product_code"),
                ]:
                    if line.startswith(field):
                        display[dkey] = line.split(":", 1)[1].strip()
            if display:
                info["display"] = display
    except Exception:
        pass

    # CEC bus state
    if os.path.exists("/dev/cec0"):
        try:
            r = subprocess.run(
                ["sudo", "cec-ctl", "-d", "/dev/cec0", "--playback", "-S"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if r.returncode == 0:
                cec: dict = {}
                for line in r.stdout.splitlines():
                    line = line.strip()
                    if "Physical Address" in line:
                        cec["physical_address"] = line.split(":", 1)[1].strip()
                    elif "OSD Name" in line:
                        cec["osd_name"] = line.split(":", 1)[1].strip().strip("'")
                    elif "Adapter Name" in line:
                        cec["adapter"] = line.split(":", 1)[1].strip()
                info["cec"] = cec
        except Exception:
            pass

    # Display modes (wlr-randr)
    display_modes, primary_output = _detect_display_modes()
    if display_modes:
        info["display_modes"] = display_modes
    if primary_output:
        info["primary_output"] = primary_output

    logger.info("Hardware info collected: %s", list(info.keys()))
    return info
