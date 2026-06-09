#!/usr/bin/env python3
"""kio Pi agent — controls Chromium via CDP and communicates over MQTT/HTTP."""

import glob
import hashlib
import json
import logging
import os
import queue
import random
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
import requests
import urllib3
import websocket
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("kio-agent")

CONFIG_FILE = "/etc/kio/kiosk.yaml"
SETTINGS_FILE = "/etc/kio/settings.json"
CDP_BASE = "http://localhost:9222"
_agent: "KioAgent | None" = None
TLS_VERIFY: bool = True  # set from config at startup

def _read_version() -> str:
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        return open(os.path.join(here, "VERSION")).read().strip()
    except Exception:
        return "unknown"

AGENT_VERSION = _read_version()

def _read_boot_id() -> str:
    try:
        return open("/proc/sys/kernel/random/boot_id").read().strip()
    except Exception:
        return "unknown"

BOOT_ID = _read_boot_id()


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def save_features(features: list[str]) -> None:
    try:
        with open(CONFIG_FILE) as f:
            cfg = yaml.safe_load(f)
        cfg["features"] = features
        with open(CONFIG_FILE, "w") as f:
            yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
        logger.info("Features persisted to config: %s", features)
    except PermissionError:
        logger.warning("Permission denied writing features to %s", CONFIG_FILE)
        _report_file_error(CONFIG_FILE)
    except Exception as exc:
        logger.warning("Failed to persist features to config: %s", exc)


STATE_FILE = "/etc/kio/hardware-state.json"


def _display_fingerprint() -> str:
    """Stable hash of the connected display's EDID, or '' if no display is connected.

    Reads the raw EDID straight from sysfs, so it works regardless of whether the
    display speaks DDC/CI (Samsung TVs don't). The hash changes only when a
    different physical display is plugged in — that's the "serious drift" signal
    that justifies re-detecting capabilities.
    """
    for path in sorted(glob.glob("/sys/class/drm/card*-HDMI-A-*/edid")):
        try:
            with open(path, "rb") as f:
                data = f.read()
            if data:  # non-empty EDID == a display is present on this connector
                return hashlib.sha256(data).hexdigest()[:16]
        except Exception:
            continue
    return ""


def _load_hw_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_hw_state(state: dict) -> None:
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except PermissionError:
        logger.warning("Permission denied writing %s", STATE_FILE)
    except Exception as exc:
        logger.warning("Failed to persist hardware state: %s", exc)


def save_settings(settings: dict) -> None:
    """Persist the last settings pulled from the API so they survive a restart
    even if the API is unreachable on the next boot."""
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f)
        logger.info("Settings persisted to %s", SETTINGS_FILE)
    except PermissionError:
        logger.warning("Permission denied writing %s", SETTINGS_FILE)
        _report_file_error(SETTINGS_FILE)
    except Exception as exc:
        logger.warning("Failed to persist settings: %s", exc)


def load_local_settings() -> dict:
    try:
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def load_config() -> dict:
    with open(CONFIG_FILE) as f:
        cfg = yaml.safe_load(f)
    raw_features = cfg.get("features") or []
    if isinstance(raw_features, str):
        raw_features = [f.strip() for f in raw_features.split(",") if f.strip()]
    api = cfg.get("api") or {}
    mqtt_cfg = cfg.get("mqtt") or {}
    return {
        # kiosk_id is optional in config: the token is the node's identity and the
        # API resolves the id from it at startup (see resolve_kiosk_id). A value
        # here is used only as a fallback if the API is unreachable on boot.
        "kiosk_id":     cfg.get("id") or "",
        "api_url":      api["url"].rstrip("/"),
        "api_token":    api["token"],
        "tls_verify":   api.get("tls_verify", True),
        "mqtt_host":    mqtt_cfg.get("host", ""),
        "mqtt_port":    int(mqtt_cfg.get("port", 1883)),
        "topic_prefix": mqtt_cfg.get("topic_prefix", "kio/prd"),
        "features":     raw_features,
        "start_url":    cfg.get("start_url") or "about:blank",
    }


def resolve_kiosk_id(cfg: dict) -> str:
    """Resolve this node's kiosk_id from the API using its token.

    The token is the node's identity; the API maps it to the kiosk and returns the
    id (and MQTT settings) from GET /agent/config. Kept in the agent's runtime so
    the id doesn't have to be hard-coded in the config. Falls back to a config-
    provided id if the API can't be reached; otherwise retries with backoff.
    """
    fallback = cfg.get("kiosk_id") or ""
    delay = 5
    attempts = 0
    while True:
        attempts += 1
        try:
            r = requests.get(
                f"{cfg['api_url']}/agent/config",
                headers={"Authorization": f"Bearer {cfg['api_token']}"},
                timeout=10, verify=cfg["tls_verify"],
            )
            if r.status_code == 200:
                data = r.json()
                kid = data.get("kiosk_id") or ""
                if kid:
                    # Adopt MQTT settings the API advertises when config omits them.
                    if data.get("mqtt_topic_prefix"):
                        cfg["topic_prefix"] = data["mqtt_topic_prefix"]
                    if not cfg.get("mqtt_host") and data.get("mqtt_host"):
                        cfg["mqtt_host"] = data["mqtt_host"]
                    if not cfg.get("mqtt_port") and data.get("mqtt_port"):
                        cfg["mqtt_port"] = int(data["mqtt_port"])
                    logger.info("Resolved kiosk_id from API: %s", kid)
                    return kid
            logger.warning("Could not resolve kiosk_id (HTTP %s)", r.status_code)
        except Exception as exc:
            logger.warning("kiosk_id resolution failed: %s", exc)
        if fallback:
            logger.warning("Using kiosk_id from config as fallback: %s", fallback)
            return fallback
        logger.warning("No kiosk_id in config and API unreachable — retrying in %ss", delay)
        time.sleep(delay)
        delay = min(delay * 2, 60)


# ---------------------------------------------------------------------------
# CDP helpers
# ---------------------------------------------------------------------------

def _get_tab() -> dict | None:
    try:
        resp = requests.get(f"{CDP_BASE}/json", timeout=2)
        tabs = [t for t in resp.json() if t.get("type") == "page"]
        return tabs[0] if tabs else None
    except Exception as exc:
        logger.warning("CDP unreachable: %s", exc)
        return None


def _wait_for_chromium(timeout: float = 60.0) -> bool:
    """Block until Chromium is ready to be controlled over CDP, or until timeout.

    Checks the browser-level WebSocket endpoint (/json/version), not just /json:
    the tab-list endpoint answers a moment before the browser WS — which is what
    Target.createTarget (opening tabs) actually needs — is ready. Waiting on the
    weaker signal let playlist preloads run too early and fail with 'no browser WS
    url available', collapsing the playlist to a single tab. Used at boot resume
    and before every playlist preload.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _browser_ws_url():
            return True
        time.sleep(2)
    return False


def _tab_info(tab: dict) -> dict:
    """Per-tab runtime info read from the page itself: seconds since it last loaded
    (via its performance clock, so it reflects real reloads) and whether it's the
    visible/foreground tab. Falls back to unknown values if it can't be read."""
    try:
        r = _cdp_call(tab, "Runtime.evaluate", {
            "expression": "({age: Math.round((Date.now() - performance.timeOrigin) / 1000),"
                          " active: document.visibilityState === 'visible'})",
            "returnByValue": True,
        })
        val = (((r or {}).get("result") or {}).get("result") or {}).get("value") or {}
        age = val.get("age")
        return {"age_seconds": int(age) if age is not None else None,
                "active": bool(val.get("active"))}
    except Exception:
        return {"age_seconds": None, "active": False}


def _get_tabs() -> list[dict]:
    try:
        resp = requests.get(f"{CDP_BASE}/json", timeout=2)
        out = []
        for t in resp.json():
            if t.get("type") != "page":
                continue
            info = _tab_info(t)
            out.append({
                "id": t["id"],
                "url": t.get("url", ""),
                "title": t.get("title", ""),
                "age_seconds": info["age_seconds"],
                "active": info["active"],
            })
        return out
    except Exception as exc:
        logger.warning("CDP tabs unreachable: %s", exc)
        return []


def _cdp_call(tab: dict, method: str, params: dict | None = None) -> dict | None:
    ws_url = tab.get("webSocketDebuggerUrl")
    if not ws_url:
        return None
    payload = json.dumps({"id": 1, "method": method, "params": params or {}})
    try:
        ws = websocket.create_connection(ws_url, timeout=5)
        ws.send(payload)
        result = json.loads(ws.recv())
        ws.close()
        return result
    except Exception as exc:
        logger.error("CDP %s failed: %s", method, exc)
        return None


def navigate(url: str) -> None:
    tab = _get_tab()
    if tab:
        _cdp_call(tab, "Page.navigate", {"url": url})
        logger.info("Navigated to %s", url)
    else:
        logger.warning("navigate: no CDP tab available")


def reload_page() -> None:
    tab = _get_tab()
    if tab:
        _cdp_call(tab, "Page.reload")
        logger.info("Reloaded page")
    else:
        logger.warning("reload: no CDP tab available")


def get_current_url() -> str | None:
    tab = _get_tab()
    return tab.get("url") if tab else None


# ---------------------------------------------------------------------------
# Playlist transitions — preloaded tabs
# ---------------------------------------------------------------------------

# Installed into every preloaded tab via Page.addScriptToEvaluateOnNewDocument
# and Runtime.evaluate. Hides the page immediately, then fades it in the first
# time the tab becomes visible (visibilitychange: hidden → visible). The guard
# prevents double-execution when both injection paths fire on the same document.
_FADE_IN_SOURCE = """\
(function () {
    if (window.__kioFadeInstalled) return;
    window.__kioFadeInstalled = true;
    var el = document.documentElement;
    el.style.opacity = '0';
    el.style.transition = '';
    function fadeIn() {
        el.style.transition = 'opacity 0.5s ease';
        el.style.opacity = '1';
    }
    if (document.visibilityState === 'visible') {
        if (document.readyState === 'complete') { fadeIn(); return; }
        window.addEventListener('load', fadeIn, {once: true});
    } else {
        document.addEventListener('visibilitychange', function onViz() {
            if (document.visibilityState === 'visible') {
                document.removeEventListener('visibilitychange', onViz);
                fadeIn();
            }
        });
    }
})();
"""


def _browser_ws_url() -> str | None:
    """Return the browser-level CDP WebSocket URL (for Target.* methods)."""
    try:
        resp = requests.get(f"{CDP_BASE}/json/version", timeout=2)
        return resp.json().get("webSocketDebuggerUrl")
    except Exception as exc:
        logger.warning("Failed to read browser WS url: %s", exc)
        return None


def _open_tab(url: str) -> dict | None:
    """Open a new background tab and return the full CDP tab dict, or None on failure.

    Uses Target.createTarget over the browser-level WebSocket. The HTTP
    /json/new endpoint was restricted in modern Chromium (returns an empty body
    over GET), so the WebSocket path is the version-stable way to create tabs.
    """
    ws_url = _browser_ws_url()
    if not ws_url:
        logger.warning("_open_tab: no browser WS url available for %s", url)
        return None

    # Create the target in the background so the active tab keeps showing.
    payload = json.dumps({
        "id": 1,
        "method": "Target.createTarget",
        "params": {"url": url, "background": True},
    })
    try:
        ws = websocket.create_connection(ws_url, timeout=5)
        ws.send(payload)
        result = json.loads(ws.recv())
        ws.close()
    except Exception as exc:
        logger.warning("Failed to open preload tab for %s: %s", url, exc)
        return None

    target_id = (result.get("result") or {}).get("targetId")
    if not target_id:
        logger.warning("_open_tab: createTarget returned no targetId (%r) for %s", result, url)
        return None

    # Resolve the full tab dict (with the page-level webSocketDebuggerUrl) from
    # the HTTP list, which GET still serves reliably.
    try:
        for t in requests.get(f"{CDP_BASE}/json", timeout=2).json():
            if t.get("id") == target_id:
                logger.info("Opened preload tab %s for %s", target_id, url)
                return t
    except Exception as exc:
        logger.warning("_open_tab: failed to resolve tab %s: %s", target_id, exc)
        return None

    logger.warning("_open_tab: tab %s not found in /json list for %s", target_id, url)
    return None


def _install_fade_script(tab: dict) -> None:
    """Install the fade-in script in a tab (best-effort, non-blocking)."""
    # Persistent: runs before page JS on every future navigation within this tab
    _cdp_call(tab, "Page.addScriptToEvaluateOnNewDocument", {"source": _FADE_IN_SOURCE})
    # Current document: handles the race where the page loads before the above lands
    _cdp_call(tab, "Runtime.evaluate", {"expression": _FADE_IN_SOURCE})


def _activate_tab(tab_id: str) -> bool:
    try:
        requests.get(f"{CDP_BASE}/json/activate/{tab_id}", timeout=3)
        return True
    except Exception as exc:
        logger.warning("Failed to activate tab %s: %s", tab_id, exc)
        return False


def _close_tab(tab_id: str) -> None:
    try:
        requests.get(f"{CDP_BASE}/json/close/{tab_id}", timeout=3)
    except Exception as exc:
        logger.debug("Failed to close tab %s: %s", tab_id, exc)


def _reload_tab(tab: dict) -> bool:
    """Reload a preloaded tab's page in place (keeps playlist content fresh)."""
    if _cdp_call(tab, "Page.reload", {}) is not None:
        return True
    logger.debug("Failed to reload tab %s", tab.get("id"))
    return False


# How often each playlist tab is reloaded in the background to keep its content
# fresh. Decoupled from item duration so pages refresh on a steady cadence rather
# than reloading on every rotation. Overridable per play via the command payload.
PLAYLIST_REFRESH_SECONDS = 300


# ---------------------------------------------------------------------------
# Playlist player
# ---------------------------------------------------------------------------

class PlaylistPlayer:
    """Cycles through playlist items by switching between preloaded browser tabs.

    All URLs are opened as background tabs before playback begins so every
    transition is an instant tab activation rather than a page load. The
    incoming tab fades in via a visibilitychange listener installed through CDP.
    On stop, the current tab stays visible; all other preloaded tabs are closed.

    A background refresh loop reloads the tabs on a steady cadence
    (refresh_seconds) so their content stays current without reloading on every
    rotation; it reloads tabs while they're hidden to avoid a visible flash.

    Commands are delivered via an internal queue so goto() can interrupt a
    sleeping duration without polling.
    """

    def __init__(self, playlist_id: str, items: list[dict], playlist_name: str = "",
                 start_idx: int = 0, refresh_seconds: int = PLAYLIST_REFRESH_SECONDS) -> None:
        self.playlist_id = playlist_id
        self._playlist_name = playlist_name or playlist_id
        self._items = items
        self._start_idx = start_idx
        self._refresh_seconds = refresh_seconds
        self._tabs: list[dict] = []   # ordered CDP tab dicts, one per item
        self._current_idx = 0
        self._item_started_at: float = 0.0
        self._lock = threading.Lock()
        self._cmd: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._next_refresh: dict[str, float] = {}  # tab id -> epoch time of next reload
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._refresh_thread = threading.Thread(target=self._refresh_loop, daemon=True)

    def start(self) -> None:
        self._preload()
        self._thread.start()
        if self._refresh_seconds > 0:
            self._refresh_thread.start()

    def stop(self) -> None:
        """Signal the play + refresh loops to exit, then close all background tabs."""
        self._stop_event.set()
        self._cmd.put(("stop", None))
        self._thread.join(timeout=2)
        with self._lock:
            active_id = self._tabs[self._current_idx]["id"] if self._tabs else None
            to_close = [t["id"] for t in self._tabs if t["id"] != active_id]
            self._tabs = []
        for tab_id in to_close:
            _close_tab(tab_id)

    def _next_refresh_at(self) -> float:
        """A refresh time one interval out, with ±20% jitter so tabs don't all
        reload at the same instant."""
        jitter = self._refresh_seconds * 0.2
        return time.time() + self._refresh_seconds + random.uniform(-jitter, jitter)

    def _refresh_tab(self, tab: dict) -> None:
        """Reload one tab and schedule its next refresh."""
        _reload_tab(tab)
        with self._lock:
            self._next_refresh[tab["id"]] = self._next_refresh_at()

    def _refresh_loop(self) -> None:
        """Reload each tab on its own jittered cadence so content stays fresh.

        Only background tabs are reloaded (never the visible one) so a refresh
        always lands *before* a tab becomes active and never flashes the screen;
        the visible tab is refreshed once it rotates out. A single-tab playlist has
        nothing to hide behind, so it's reloaded in place. The rotation loop also
        pre-refreshes the on-deck tab (see _run) to maximise lead time.
        """
        poll = max(2, min(15, self._refresh_seconds // 4))
        while not self._stop_event.wait(poll):
            now = time.time()
            with self._lock:
                tabs = list(self._tabs)
                active_id = tabs[self._current_idx]["id"] if tabs else None
                due = [t for t in tabs
                       if now >= self._next_refresh.get(t["id"], 0)
                       and (len(tabs) <= 1 or t["id"] != active_id)]
            for tab in due:
                if self._stop_event.is_set():
                    break
                self._refresh_tab(tab)

    def _prerefresh_on_deck(self, idx: int) -> None:
        """Refresh the tab that will be shown next, if it's due — giving it the
        current item's full duration to reload while still hidden."""
        if self._refresh_seconds <= 0:
            return
        with self._lock:
            n = len(self._tabs)
            if n <= 1:
                return
            on_deck = self._tabs[(idx + 1) % n]
            active_id = self._tabs[self._current_idx]["id"]
            due = (time.time() >= self._next_refresh.get(on_deck["id"], 0)
                   and on_deck["id"] != active_id)
        if due:
            self._refresh_tab(on_deck)

    def goto(self, idx: int) -> None:
        """Jump to a specific playlist item by index, resetting its duration timer."""
        self._cmd.put(("goto", idx))

    def current_state(self) -> dict:
        with self._lock:
            return {
                "idx": self._current_idx,
                "started_at": datetime.fromtimestamp(
                    self._item_started_at, tz=timezone.utc
                ).isoformat() if self._item_started_at else None,
                "total": len(self._items),
            }

    def _preload(self) -> None:
        # Wait for Chromium to be controllable — playback is often resumed right
        # after boot before the browser is ready, which would otherwise drop tabs.
        if not _wait_for_chromium():
            logger.warning("Playlist %s: browser not ready after wait; preload may be incomplete",
                           self.playlist_id)
        loaded_items: list[dict] = []
        loaded_tabs: list[dict] = []
        for item in self._items:
            tab = _open_tab(item["url"])
            if tab:
                _install_fade_script(tab)
                loaded_tabs.append(tab)
                loaded_items.append(item)
        # Keep items and tabs in sync so goto indices always match
        self._items = loaded_items
        self._tabs = loaded_tabs
        # Close any pre-existing tabs (the start_url tab, leftovers from a previous
        # playlist) so only this playlist's tabs remain. Without this, tabs pile up
        # across plays — duplicates and orphans the dashboard shows as stale tabs.
        # Guard: only prune once we actually have new tabs, so a failed preload
        # never leaves a blank browser.
        if loaded_tabs:
            keep_ids = {t["id"] for t in loaded_tabs}
            for existing in _get_tabs():
                if existing["id"] not in keep_ids:
                    _close_tab(existing["id"])
        # Stagger each tab's first refresh across the interval (plus jitter) so they
        # don't all reload together once the cadence kicks in.
        if self._refresh_seconds > 0 and loaded_tabs:
            now = time.time()
            n = len(loaded_tabs)
            for i, tab in enumerate(loaded_tabs):
                spread = self._refresh_seconds * ((i + 1) / n)
                self._next_refresh[tab["id"]] = now + spread + random.uniform(0, self._refresh_seconds * 0.1)
        logger.info(
            "Playlist %s preloaded %d/%d tabs",
            self.playlist_id, len(self._tabs), len(self._items),
        )

    def _run(self) -> None:
        if not self._tabs:
            logger.warning("Playlist %s: no tabs preloaded, aborting", self.playlist_id)
            return
        logger.info("Playlist %s starting (%d tabs)", self.playlist_id, len(self._tabs))

        n = len(self._items)
        idx = min(self._start_idx, n - 1)
        with self._lock:
            self._current_idx = idx
            self._item_started_at = time.time()
        _activate_tab(self._tabs[idx]["id"])

        while True:
            item = self._items[idx]
            duration = item["duration_seconds"]
            logger.info(
                "Playlist %s [%d/%d] %s for %ds",
                self.playlist_id, idx + 1, n, item["url"], duration,
            )

            # Refresh the next tab now (while hidden) if it's due, so it's freshly
            # loaded by the time it rotates in.
            self._prerefresh_on_deck(idx)

            try:
                cmd, arg = self._cmd.get(timeout=duration)
            except queue.Empty:
                # Duration elapsed normally — advance to next item
                idx = (idx + 1) % n
                with self._lock:
                    self._current_idx = idx
                    self._item_started_at = time.time()
                next_url = self._items[idx].get("url", "?")
                if not _activate_tab(self._tabs[idx]["id"]):
                    logger.warning("Playlist %s auto-advance to [%d] %s: tab activation failed",
                                   self._playlist_name, idx + 1, next_url)
                    _report_command(
                        f"playlist_advance: {self._playlist_name} [{idx + 1}] {next_url}",
                        False, "Tab activation failed",
                    )
                continue

            if cmd == "stop":
                break
            elif cmd == "goto":
                target = max(0, min(arg, n - 1))
                item_url = self._items[target].get("url", "?")
                with self._lock:
                    self._current_idx = target
                    self._item_started_at = time.time()
                idx = target
                ok = _activate_tab(self._tabs[idx]["id"])
                logger.info("Playlist %s goto [%d] %s (%s)",
                            self._playlist_name, idx + 1, item_url, "ok" if ok else "FAILED")
                _report_command(
                    f"playlist_goto: {self._playlist_name} [{idx + 1}] {item_url}",
                    ok,
                    None if ok else "Tab activation failed",
                )

        logger.info("Playlist %s stopped", self.playlist_id)


# ---------------------------------------------------------------------------
# Command handler
# ---------------------------------------------------------------------------

def detect_capabilities() -> tuple[list[str], dict]:
    """Probe hardware and return (capabilities, probes) where probes has per-check debug info."""
    caps: list[str] = []
    probes: dict = {}

    # display_power: ddcutil can read/write VCP D6 (display power mode)
    try:
        r = subprocess.run(["ddcutil", "getvcp", "D6"], capture_output=True, text=True, timeout=15)
        detected = r.returncode == 0
        probes["display_power"] = {
            "cmd": "ddcutil getvcp D6",
            "returncode": r.returncode,
            "stdout": r.stdout.strip()[:1000],
            "stderr": r.stderr.strip()[:500],
            "detected": detected,
        }
        if detected:
            caps.append("display_power")
    except Exception as exc:
        probes["display_power"] = {"cmd": "ddcutil getvcp D6", "error": str(exc), "detected": False}

    # cec: /dev/cec0 exists, cec-ctl installed, and a display is on the bus
    # (physical address f.f.f.f means no CEC-capable display is connected)
    cec_cmd = ["sudo", "cec-ctl", "-d", "/dev/cec0", "--playback", "-S"]
    if os.path.exists("/dev/cec0"):
        try:
            r = subprocess.run(cec_cmd, capture_output=True, text=True, timeout=10)
            physical = next(
                (l.split(":", 1)[1].strip() for l in r.stdout.splitlines() if "Physical Address" in l),
                "unknown",
            )
            detected = r.returncode == 0 and physical != "f.f.f.f"
            probes["cec"] = {
                "cmd": " ".join(cec_cmd),
                "returncode": r.returncode,
                "stdout": r.stdout.strip()[:1000],
                "stderr": r.stderr.strip()[:500],
                "physical_address": physical,
                "detected": detected,
            }
            if detected:
                caps.append("cec")
        except Exception as exc:
            probes["cec"] = {"cmd": " ".join(cec_cmd), "error": str(exc), "detected": False}
    else:
        probes["cec"] = {"cmd": " ".join(cec_cmd), "error": "/dev/cec0 not found", "detected": False}

    # input_switch: ddcutil can read VCP 60 (input source)
    try:
        r = subprocess.run(["ddcutil", "getvcp", "60"], capture_output=True, text=True, timeout=15)
        detected = r.returncode == 0
        probes["input_switch"] = {
            "cmd": "ddcutil getvcp 60",
            "returncode": r.returncode,
            "stdout": r.stdout.strip()[:1000],
            "stderr": r.stderr.strip()[:500],
            "detected": detected,
        }
        if detected:
            caps.append("input_switch")
    except Exception as exc:
        probes["input_switch"] = {"cmd": "ddcutil getvcp 60", "error": str(exc), "detected": False}

    logger.info("Detected capabilities: %s", caps)
    return caps, probes


def collect_hardware_info() -> dict:
    """Gather detailed hardware information about this node."""
    info: dict = {}

    # OS
    try:
        info["kernel"] = subprocess.run(
            ["uname", "-r"], capture_output=True, text=True, timeout=5
        ).stdout.strip()
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
            val = next((l.split(":", 1)[1].strip() for l in cpuinfo.splitlines() if l.startswith(f"{label}\t")), None)
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
                capture_output=True, text=True, timeout=10,
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

    logger.info("Hardware info collected: %s", list(info.keys()))
    return info


def _report_hardware_info(hw_info: dict) -> None:
    if not _agent:
        return
    try:
        requests.put(
            f"{_agent.api_url}/agent/meta/hardware_info",
            json={"value": hw_info},
            headers={"Authorization": f"Bearer {_agent.api_token}"},
            timeout=10,
            verify=TLS_VERIFY,
        )
    except Exception as exc:
        logger.warning("Failed to report hardware info: %s", exc)


def _report_detect_log(caps: list[str], probes: dict, hw_info: dict) -> None:
    if not _agent:
        return
    try:
        requests.post(
            f"{_agent.api_url}/agent/hardware-detect-log",
            json={"capabilities": caps, "probes": probes, "hardware_info": hw_info},
            headers={"Authorization": f"Bearer {_agent.api_token}"},
            timeout=10,
            verify=TLS_VERIFY,
        )
    except Exception as exc:
        logger.warning("Failed to report detect log: %s", exc)


INPUT_MAP = {
    "dp1":   "0x0f",
    "dp2":   "0x10",
    "hdmi1": "0x11",
    "hdmi2": "0x12",
}

WAYLAND_ENV = {**os.environ, "WAYLAND_DISPLAY": "wayland-0"}


def _cec_phys_addr() -> str:
    """This adapter's CEC physical address (e.g. '4.0.0.0'), or '' if unallocated."""
    try:
        r = subprocess.run(
            ["sudo", "cec-ctl", "-d", "/dev/cec0", "--playback"],
            capture_output=True, text=True, timeout=10,
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
    TVs), and for explicit wake/standby commands. on → one-touch-play (wake the
    TV and announce ourselves as active source); off → standby the TV.
    """
    if not os.path.exists("/dev/cec0"):
        return False
    if on:
        r = subprocess.run(
            ["sudo", "cec-ctl", "-d", "/dev/cec0", "--playback", "-t", "0", "--image-view-on"],
            capture_output=True, text=True, timeout=10,
        )
        addr = _cec_phys_addr()
        if addr:
            subprocess.run(
                ["sudo", "cec-ctl", "-d", "/dev/cec0", "--playback", "--active-source", f"phys-addr={addr}"],
                capture_output=True, text=True, timeout=10,
            )
        return r.returncode == 0
    r = subprocess.run(
        ["sudo", "cec-ctl", "-d", "/dev/cec0", "--playback", "-t", "0", "--standby"],
        capture_output=True, text=True, timeout=10,
    )
    return r.returncode == 0


def _wayland_env() -> dict | None:
    """Return env vars needed to talk to the running Wayland compositor, or None."""
    sockets = glob.glob("/run/user/*/wayland-0")
    if not sockets:
        return None
    uid = sockets[0].split("/")[3]
    return {**os.environ, "XDG_RUNTIME_DIR": f"/run/user/{uid}", "WAYLAND_DISPLAY": "wayland-0"}


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
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode == 0:
        logger.info("Display %s via ddcutil VCP D6=%s", "on" if on else "off", value)
    else:
        logger.warning("Display %s failed: wlopm, CEC, and ddcutil all failed", "on" if on else "off")


def _report_file_error(path: str, process: str = "agent") -> None:
    if not _agent:
        return
    try:
        requests.post(
            f"{_agent.api_url}/agent/file-permission-error",
            json={"file": path, "process": process},
            headers={"Authorization": f"Bearer {_agent.api_token}"},
            timeout=5,
            verify=TLS_VERIFY,
        )
    except Exception as exc:
        logger.debug("Failed to report file permission error: %s", exc)


def _report_command(command: str, success: bool, message: str | None = None,
                    command_id: str | None = None) -> None:
    if not _agent:
        return
    try:
        body: dict = {"command": command, "success": success, "message": message}
        if command_id:
            body["command_id"] = command_id  # API matches the dashboard record by id
        resp = requests.post(
            f"{_agent.api_url}/agent/command-log",
            json=body,
            headers={"Authorization": f"Bearer {_agent.api_token}"},
            timeout=5,
            verify=TLS_VERIFY,
        )
        if resp.status_code not in (200, 204):
            logger.warning("command-log ack returned HTTP %s for %s (id=%s)", resp.status_code, command, command_id)
        else:
            logger.info("command-log ack OK: %s success=%s (id=%s)", command, success, command_id)
    except Exception as exc:
        logger.warning("Failed to report command result for %s: %s", command, exc)


def handle_command(payload: bytes) -> None:
    try:
        cmd = json.loads(payload)
    except json.JSONDecodeError:
        logger.error("Malformed command payload: %r", payload)
        return

    command = cmd.get("command")
    command_id = cmd.get("command_id")  # echoed back so the API matches by id
    logger.info("Received command: %s", command)

    try:
        if command == "play_playlist":
            items = cmd.get("items", [])
            playlist_id = cmd.get("playlist_id", "unknown")
            playlist_name = cmd.get("playlist_name", "") or playlist_id
            refresh_seconds = int(cmd.get("refresh_seconds", PLAYLIST_REFRESH_SECONDS))
            if items and _agent:
                _agent._start_playlist(playlist_id, items, playlist_name=playlist_name,
                                       refresh_seconds=refresh_seconds)
            else:
                logger.warning("play_playlist: missing items or agent not ready")
        elif command == "stop_playlist":
            if _agent:
                _agent._stop_playlist()
        elif command == "sync_playlist":
            items = cmd.get("items", [])
            playlist_id = cmd.get("playlist_id", "unknown")
            playlist_name = cmd.get("playlist_name", "") or playlist_id
            refresh_seconds = int(cmd.get("refresh_seconds", PLAYLIST_REFRESH_SECONDS))
            if _agent and _agent._player is not None:
                logger.info("Playlist %s updated — reloading active player (%d items)", playlist_id, len(items))
                _agent._start_playlist(playlist_id, items, playlist_name=playlist_name,
                                       refresh_seconds=refresh_seconds)
            else:
                logger.info("Playlist %s updated (not currently playing, no action)", playlist_id)
        elif command == "playlist_goto":
            idx = cmd.get("index", 0)
            if _agent and _agent._player is not None:
                _agent._player.goto(idx)
            else:
                logger.warning("playlist_goto: no active playlist player")
        elif command == "open_tab":
            url = cmd.get("url", "")
            if url:
                tab = _open_tab(url)
                if tab:
                    logger.info("Opened new tab: %s", url)
                else:
                    logger.warning("open_tab: failed to create tab for %s", url)
                    _report_command(f"open_tab: {url}", False, "Tab creation failed", command_id=command_id)
                    return
            else:
                logger.warning("open_tab: no URL provided")
                _report_command("open_tab", False, "No URL provided", command_id=command_id)
                return
        elif command == "close_tab":
            tab_id = cmd.get("tab_id", "")
            if not tab_id:
                logger.warning("close_tab: no tab_id provided")
                _report_command("close_tab", False, "No tab_id provided", command_id=command_id)
                return
            # Closing the last remaining tab quits Chromium (the window closes).
            # Instead, navigate it to the node's default page so the kiosk keeps
            # showing something. A playlist takeover is also stopped.
            page_tabs = [t for t in _get_tabs()]
            if len(page_tabs) <= 1:
                if _agent:
                    _agent._stop_playlist()
                    default_url = _agent.start_url
                else:
                    default_url = "about:blank"
                logger.info("close_tab: last tab — navigating to default %s instead of closing", default_url)
                navigate(default_url)
            else:
                requests.get(f"{CDP_BASE}/json/close/{tab_id}", timeout=5)
                logger.info("Closed tab: %s", tab_id)
        elif command == "activate_tab":
            tab_id = cmd.get("tab_id", "")
            if tab_id:
                # Focusing a tab is a manual takeover — stop any running playlist so
                # it doesn't rotate away from the tab the operator just selected.
                if _agent:
                    _agent._stop_playlist()
                requests.get(f"{CDP_BASE}/json/activate/{tab_id}", timeout=5)
                logger.info("Activated tab: %s", tab_id)
            else:
                logger.warning("activate_tab: no tab_id provided")
                _report_command("activate_tab", False, "No tab_id provided", command_id=command_id)
                return
        elif command == "refresh_tab":
            tab_id = cmd.get("tab_id", "")
            if not tab_id:
                logger.warning("refresh_tab: no tab_id provided")
                _report_command("refresh_tab", False, "No tab_id provided", command_id=command_id)
                return
            try:
                tabs = {t["id"]: t for t in requests.get(f"{CDP_BASE}/json", timeout=3).json()
                        if t.get("type") == "page"}
            except Exception:
                tabs = {}
            tab = tabs.get(tab_id)
            if tab and _reload_tab(tab):
                logger.info("Refreshed tab: %s", tab_id)
            else:
                logger.warning("refresh_tab: tab %s not found or reload failed", tab_id)
                _report_command("refresh_tab", False, "Tab not found or reload failed", command_id=command_id)
                return
        elif command == "navigate_tab":
            tab_id = cmd.get("tab_id", "")
            url = cmd.get("url", "")
            if tab_id and url:
                try:
                    resp = requests.get(f"{CDP_BASE}/json", timeout=2)
                    tabs = {t["id"]: t for t in resp.json() if t.get("type") == "page"}
                    tab = tabs.get(tab_id)
                    if tab:
                        _cdp_call(tab, "Page.navigate", {"url": url})
                        logger.info("Navigated tab %s to %s", tab_id, url)
                    else:
                        logger.warning("navigate_tab: tab %s not found", tab_id)
                        _report_command("navigate_tab", False, f"Tab {tab_id} not found", command_id=command_id)
                        return
                except Exception as exc:
                    logger.error("navigate_tab failed: %s", exc)
                    _report_command("navigate_tab", False, str(exc), command_id=command_id)
                    return
            else:
                logger.warning("navigate_tab: missing tab_id or url")
                _report_command("navigate_tab", False, "Missing tab_id or url", command_id=command_id)
                return
        elif command == "sync_browser_flags":
            if _agent:
                _agent._sync_browser_flags()
            else:
                logger.warning("sync_browser_flags: agent not ready")
        elif command == "sync_hosts":
            if _agent:
                _agent._sync_hosts()
            else:
                logger.warning("sync_hosts: agent not ready")
        elif command == "sync_settings":
            if _agent:
                # Pulls, persists, applies live, and logs its own event — so return
                # here rather than falling through to the generic ack below.
                _agent._sync_settings(command_id=command_id)
            else:
                logger.warning("sync_settings: agent not ready")
            return
        elif command == "detect_capabilities":
            if _agent:
                _agent._run_capability_detection()
            else:
                logger.warning("detect_capabilities: agent not ready")
        elif command == "reload":
            reload_page()
        elif command == "reboot":
            _report_command("reboot", True, command_id=command_id)
            subprocess.run(["sudo", "reboot"], check=False)
            return
        elif command == "display_off":
            _set_display_power(False)
        elif command == "display_on":
            _set_display_power(True)
        elif command == "standby":
            _cec_power(False)
            logger.info("CEC standby sent")
        elif command == "wake":
            _cec_power(True)
            logger.info("CEC wake sent")
        elif command == "set_input":
            input_name = cmd.get("input", "")
            hex_val = INPUT_MAP.get(input_name)
            if hex_val:
                subprocess.run(["ddcutil", "setvcp", "60", hex_val], check=False)
                logger.info("Input switched to %s (%s)", input_name, hex_val)
                if _agent:
                    _agent._current_input = input_name  # prevent monitor from re-reporting this change
                    try:
                        resp = requests.post(
                            f"{_agent.api_url}/agent/heartbeat",
                            json={"online": True, "current_url": get_current_url(), "current_input": input_name, "display_on": _agent._get_display_on()},
                            headers={"Authorization": f"Bearer {_agent.api_token}"},
                            timeout=10,
                            verify=TLS_VERIFY,
                        )
                        logger.info("Input heartbeat OK (HTTP %s)", resp.status_code)
                    except Exception as exc:
                        logger.warning("Input heartbeat failed: %s", exc)
            else:
                logger.warning("Unknown input: %s", input_name)
                _report_command(f"set_input: {input_name}", False, "Unknown input", command_id=command_id)
                return
        else:
            logger.warning("Unknown command: %s", command)
            _report_command(command or "unknown", False, "Unknown command", command_id=command_id)
            return

        # The dashboard already recorded a human-readable label; the agent only
        # needs to ack by id (or by bare command name for agent-initiated commands).
        _report_command(command or "unknown", True, command_id=command_id)

    except Exception as exc:
        logger.error("Command %s failed: %s", command, exc)
        _report_command(command or "unknown", False, str(exc), command_id=command_id)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class KioAgent:
    def __init__(self, config: dict) -> None:
        self.kiosk_id:     str       = config["kiosk_id"]
        self.api_url:      str       = config["api_url"]
        self.api_token:    str       = config["api_token"]
        self.mqtt_host:    str       = config["mqtt_host"]
        self.mqtt_port:    int       = config["mqtt_port"]
        self.topic_prefix: str       = config["topic_prefix"]
        self.features:     list[str] = config["features"]
        self.start_url:    str       = config["start_url"]
        self.command_topic = f"{self.topic_prefix}/kiosks/{self.kiosk_id}/command"
        self.nav_topic     = f"{self.topic_prefix}/kiosks/{self.kiosk_id}/nav"
        self._stop = threading.Event()
        self._player: PlaylistPlayer | None = None
        self._current_input: str | None = None  # synced by set_input + monitor thread
        # Dispatch MQTT command handling off the network loop thread so long-running
        # operations (preload, wait_for_chromium) don't block keepalive ping/pong.
        self._cmd_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mqtt-cmd")

        # Server-tunable settings (see GET /agent/settings). Seeded with defaults
        # so the heartbeat/checkin loops work before the first successful fetch;
        # refreshed on boot and every settings_checkin_seconds thereafter.
        self._hb_interval        = 30
        self._hb_jitter          = 0
        self._metadata_interval  = 3600
        self._settings_checkin   = 300

        env_tag = self.topic_prefix.replace("/", "-")
        self.client = mqtt.Client(
            client_id=f"{env_tag}-{self.kiosk_id[:8]}",
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        )
        self.client.on_connect    = self._on_connect
        self.client.on_message    = self._on_message
        self.client.on_disconnect = self._on_disconnect

    # --- Playlist control ---

    def _resume_state(self) -> None:
        """Fetch the kiosk's last active state from the API and resume it.

        Called once at boot, before the first heartbeat, so the pre-reboot
        playlist_state is still in the database and can be read here.
        """
        try:
            resp = requests.get(
                f"{self.api_url}/agent/state",
                headers={"Authorization": f"Bearer {self.api_token}"},
                timeout=10,
                verify=TLS_VERIFY,
            )
            if resp.status_code != 200:
                logger.warning("Boot resume: state endpoint returned HTTP %s", resp.status_code)
                return
            state = resp.json()
        except Exception as exc:
            logger.warning("Boot resume: failed to fetch state: %s", exc)
            return

        playlist = state.get("playlist")
        if not playlist or not playlist.get("items"):
            logger.info("Boot resume: no active playlist to resume")
            return

        last_idx = playlist.get("last_idx") or 0
        logger.info(
            "Boot resume: waiting for Chromium, then resuming playlist '%s' at item %d",
            playlist["name"], last_idx + 1,
        )
        if not _wait_for_chromium():
            logger.warning("Boot resume: Chromium not ready after timeout, skipping")
            return

        self._start_playlist(
            playlist["id"],
            playlist["items"],
            playlist_name=playlist["name"],
            start_idx=last_idx,
            refresh_seconds=int(playlist.get("refresh_seconds", PLAYLIST_REFRESH_SECONDS)),
        )

    def _stop_playlist(self) -> None:
        if self._player is not None:
            self._player.stop()
            self._player = None

    def _start_playlist(self, playlist_id: str, items: list[dict], playlist_name: str = "",
                        start_idx: int = 0, refresh_seconds: int = PLAYLIST_REFRESH_SECONDS) -> None:
        self._stop_playlist()
        self._player = PlaylistPlayer(playlist_id, items, playlist_name=playlist_name,
                                      start_idx=start_idx, refresh_seconds=refresh_seconds)
        self._player.start()

    # --- HTTP heartbeat ---

    def _sync_hosts(self) -> None:
        try:
            resp = requests.get(
                f"{self.api_url}/agent/meta",
                headers={"Authorization": f"Bearer {self.api_token}"},
                timeout=10,
                verify=TLS_VERIFY,
            )
            if resp.status_code != 200:
                return
            hosts = resp.json().get("extra_hosts", [])
            with open("/etc/kio/extra-hosts", "w") as f:
                f.write("\n".join(hosts) + "\n" if hosts else "")
            result = subprocess.run(
                ["sudo", "/opt/kio-agent/update-hosts"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                logger.info("Hosts synced: %d entries", len(hosts))
            else:
                logger.warning("Hosts update failed: %s", result.stderr.strip())
        except PermissionError:
            logger.warning("Permission denied writing /etc/kio/extra-hosts")
            _report_file_error("/etc/kio/extra-hosts")
        except Exception as exc:
            logger.warning("Hosts sync failed: %s", exc)

    def _sync_browser_flags(self) -> None:
        flags_file = "/etc/kio/browser-flags"
        try:
            resp = requests.get(
                f"{self.api_url}/agent/browser-flags",
                headers={"Authorization": f"Bearer {self.api_token}"},
                timeout=10,
                verify=TLS_VERIFY,
            )
            if resp.status_code == 200:
                flags = resp.json()
                current = ""
                try:
                    current = open(flags_file).read()
                except FileNotFoundError:
                    pass
                new_content = "\n".join(flags) + "\n"
                if new_content != current:
                    with open(flags_file, "w") as f:
                        f.write(new_content)
                    logger.info("Browser flags updated: %s", flags)
            else:
                logger.warning("Failed to fetch browser flags: HTTP %s", resp.status_code)
        except PermissionError:
            logger.warning("Permission denied writing %s", flags_file)
            _report_file_error(flags_file)
        except Exception as exc:
            logger.warning("Browser flags sync failed: %s", exc)

    def _get_current_input(self) -> str | None:
        try:
            result = subprocess.run(
                ["ddcutil", "getvcp", "60"],
                capture_output=True, text=True, timeout=10,
            )
            import re
            m = re.search(r'sl=0x([0-9a-fA-F]+)', result.stdout)
            if m:
                reverse = {"0f": "dp1", "10": "dp2", "11": "hdmi1", "12": "hdmi2"}
                return reverse.get(m.group(1).lower())
        except Exception as exc:
            logger.debug("ddcutil getvcp failed: %s", exc)
        return None

    def _get_display_on(self) -> bool | None:
        """Read display power state. Tries CEC → DDC → Wayland in order.

        CEC is checked first because it reflects the TV's actual power state —
        wlopm only reports whether the compositor output is active (which is
        always True while labwc is running, even when the TV is off via CEC).
        """
        # CEC: gives the TV's real power state, not just signal presence.
        if os.path.exists("/dev/cec0"):
            try:
                r = subprocess.run(
                    ["sudo", "cec-ctl", "-d", "/dev/cec0", "--playback", "-t", "0", "--give-device-power-status"],
                    capture_output=True, text=True, timeout=10,
                )
                for line in r.stdout.splitlines():
                    if "pwr-state" in line.lower():
                        return "on" in line.lower()
            except Exception as exc:
                logger.debug("cec power status failed: %s", exc)
        # DDC: works for monitors that support VCP D6 while awake.
        try:
            import re
            result = subprocess.run(
                ["ddcutil", "getvcp", "D6"],
                capture_output=True, text=True, timeout=10,
            )
            m = re.search(r'sl=0x([0-9a-fA-F]+)', result.stdout)
            if m:
                return int(m.group(1), 16) == 1
        except Exception as exc:
            logger.debug("ddcutil getvcp D6 failed: %s", exc)
        # Wayland: reflects compositor output state, not physical display power.
        # Useful for monitors without DDC/CEC, but always True on running labwc.
        env = _wayland_env()
        if env and os.path.exists("/usr/bin/wlopm"):
            try:
                r = subprocess.run(["wlopm"], capture_output=True, text=True, timeout=5, env=env)
                states = [line.split()[1] for line in r.stdout.strip().splitlines() if len(line.split()) >= 2]
                if states:
                    return any(s == "on" for s in states)
            except Exception as exc:
                logger.debug("wlopm state read failed: %s", exc)
        return None

    def _get_device_type(self) -> str:
        try:
            model = open("/proc/device-tree/model").read().rstrip("\x00").strip()
            return model
        except Exception:
            return "unknown"

    def _get_ip_address(self) -> str:
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "unknown"

    def _post_heartbeat(self, online: bool = True, include_metadata: bool = False,
                        include_features: bool = False) -> None:
        # Hardware state (ddcutil/CEC) is slow — only poll on the hourly metadata
        # heartbeat so routine 30s ticks stay fast and don't block tab/URL updates.
        payload: dict = {
            "online":         online,
            "agent_version":  AGENT_VERSION,
            "boot_id":        BOOT_ID,
            "current_url":    get_current_url() if online else None,
            "browser_tabs":   _get_tabs() if online else [],
            "playlist_state": self._player.current_state() if self._player is not None else None,
        }
        if include_metadata or not online:
            payload["current_input"] = self._get_current_input() if online else None
            payload["display_on"]    = self._get_display_on()    if online else False
        # Features are admin-authoritative: only reported when we have a deliberate
        # reason to update them (explicit detect, or detected display drift), never
        # on routine heartbeats — otherwise they'd clobber dashboard edits hourly.
        if include_features:
            payload["features"] = self.features
        if include_metadata:
            payload["device_type"] = self._get_device_type()
            payload["ip_address"]  = self._get_ip_address()
            logger.info(
                "Heartbeat [full] online=%s url=%s input=%s display=%s features=%s device=%s ip=%s",
                online,
                payload.get("current_url"),
                payload.get("current_input"),
                payload.get("display_on"),
                self.features if include_features else "(unchanged)",
                payload.get("device_type"),
                payload.get("ip_address"),
            )
        else:
            logger.info(
                "Heartbeat online=%s url=%s tabs=%d",
                online,
                payload.get("current_url"),
                len(payload.get("browser_tabs") or []),
            )

        try:
            resp = requests.post(
                f"{self.api_url}/agent/heartbeat",
                json=payload,
                headers={"Authorization": f"Bearer {self.api_token}"},
                timeout=10,
                verify=TLS_VERIFY,
            )
            if resp.status_code == 204:
                logger.info("Heartbeat OK")
            else:
                logger.warning("Heartbeat FAILED: HTTP %s", resp.status_code)
        except Exception as exc:
            logger.warning("Heartbeat FAILED: %s", exc)

    def _run_capability_detection(self) -> None:
        """Probe hardware, update features, and report — the deliberate update path.

        Used by the explicit 'detect_capabilities' command and by display-drift
        detection. This is the ONLY routine that overwrites the dashboard's
        features, and it also records the display fingerprint it detected against.
        """
        caps, probes = detect_capabilities()
        hw_info = collect_hardware_info()
        self.features = caps
        save_features(caps)
        _report_hardware_info(hw_info)
        _report_detect_log(caps, probes, hw_info)
        self._post_heartbeat(include_metadata=True, include_features=True)
        state = _load_hw_state()
        state["display_fingerprint"] = _display_fingerprint()
        _save_hw_state(state)
        logger.info("Capabilities detected and reported: %s", caps)

    def _check_display_drift(self) -> None:
        """Re-detect capabilities only when the connected display actually changes.

        Features are otherwise left untouched so dashboard/admin edits stick. A node
        with no recorded display just records its fingerprint without overwriting
        existing features — initial population is done explicitly via the
        'Detect Hardware' button so we never clobber a deliberate setup on upgrade.
        """
        current = _display_fingerprint()
        if not current:
            return  # no display connected — don't touch features
        state = _load_hw_state()
        last = state.get("display_fingerprint")
        if last is None:
            state["display_fingerprint"] = current
            _save_hw_state(state)
            logger.info("Recorded initial display fingerprint %s — features left as-is", current)
            return
        if current != last:
            logger.info("Display changed (fingerprint %s -> %s) — re-detecting capabilities",
                        last, current)
            self._run_capability_detection()

    def _fetch_settings(self) -> dict:
        """Fetch this node's effective settings from the API (raises on failure)."""
        resp = requests.get(
            f"{self.api_url}/agent/settings",
            headers={"Authorization": f"Bearer {self.api_token}"},
            timeout=10,
            verify=TLS_VERIFY,
        )
        resp.raise_for_status()
        return resp.json()

    def _apply_settings(self, report: bool) -> None:
        """Fetch settings, persist them locally, and apply them to the running loops.

        Node settings are pulled on every agent restart and on a recurring
        checkin. Pulled settings are cached to SETTINGS_FILE so they survive a
        restart even when the API is unreachable; if the fetch fails we fall back
        to that cache. On the boot pull we report success/failure to the event log
        so the dashboard can see whether the node picked up its settings.
        """
        source = "api"
        try:
            s = self._fetch_settings()
            save_settings(s)
        except Exception as exc:
            cached = load_local_settings()
            if not cached:
                logger.warning("Failed to fetch settings and no local cache: %s", exc)
                if report:
                    _report_command("apply_settings", False, str(exc))
                return
            logger.info("Settings fetch failed (%s) — using local cache", exc)
            s = cached
            source = "cache"

        self._hb_interval       = max(5,  int(s.get("heartbeat_interval_seconds", self._hb_interval)))
        self._hb_jitter         = max(0,  int(s.get("heartbeat_jitter_seconds", self._hb_jitter)))
        self._metadata_interval = max(60, int(s.get("metadata_interval_seconds", self._metadata_interval)))
        self._settings_checkin  = max(30, int(s.get("settings_checkin_seconds", self._settings_checkin)))
        logger.info(
            "Applied settings from %s: heartbeat=%ds jitter=%ds metadata=%ds checkin=%ds",
            source, self._hb_interval, self._hb_jitter, self._metadata_interval, self._settings_checkin,
        )
        if report:
            _report_command(
                "apply_settings", True,
                f"[{source}] heartbeat={self._hb_interval}s jitter={self._hb_jitter}s "
                f"metadata={self._metadata_interval}s checkin={self._settings_checkin}s",
            )

    def _sync_settings(self, command_id: str | None = None) -> None:
        """Pull the latest settings from the server and apply them live.

        Triggered by the API's `sync_settings` command when an admin changes a
        node-affecting setting (global or this node's override), so changes take
        effect immediately rather than waiting for the next scheduled checkin. No
        restart is needed — the running heartbeat/checkin loops read the updated
        values on their next tick.
        """
        self._apply_settings(report=False)
        logger.info(
            "Synced settings from server (applied live): heartbeat=%ds jitter=%ds metadata=%ds checkin=%ds",
            self._hb_interval, self._hb_jitter, self._metadata_interval, self._settings_checkin,
        )
        _report_command(
            "sync_settings", True,
            f"synced from server — heartbeat={self._hb_interval}s jitter={self._hb_jitter}s "
            f"metadata={self._metadata_interval}s checkin={self._settings_checkin}s",
            command_id=command_id,
        )

    def _settings_loop(self) -> None:
        # settings_checkin can itself change, so re-read the interval each tick.
        while not self._stop.wait(self._settings_checkin):
            self._apply_settings(report=False)

    def _input_monitor_loop(self) -> None:
        """Detect external input changes (TV remote, physical buttons) and report immediately.

        Polls VCP 60 via ddcutil every 45 s. When the value differs from the last known
        input (set either by a set_input command or a previous poll), sends an immediate
        metadata heartbeat so the dashboard stays in sync without waiting for the hourly
        metadata tick. Skips polling when the display doesn't advertise input_switch capability.
        """
        while not self._stop.wait(45):
            if "input_switch" not in self.features:
                continue
            detected = self._get_current_input()
            if self._current_input is None:
                self._current_input = detected  # seed on first read, no report needed
                continue
            if detected != self._current_input:
                logger.info("Input changed externally: %s -> %s", self._current_input, detected)
                self._current_input = detected
                self._post_heartbeat(include_metadata=True)

    def _heartbeat_loop(self) -> None:
        # Track the next metadata heartbeat in monotonic time so the interval can
        # be re-tuned between ticks without drift.
        next_metadata = time.monotonic() + self._metadata_interval

        while True:
            jitter = random.uniform(0, self._hb_jitter) if self._hb_jitter else 0
            if self._stop.wait(self._hb_interval + jitter):
                break
            now = time.monotonic()
            is_meta = now >= next_metadata
            if is_meta:
                next_metadata = now + self._metadata_interval
            self._post_heartbeat(include_metadata=is_meta)
            if is_meta:
                self._check_display_drift()

    # --- MQTT callbacks (commands only) ---

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code != 0:
            logger.error("MQTT connect failed, rc=%s", reason_code)
            return
        logger.info("Connected to MQTT at %s:%s", self.mqtt_host, self.mqtt_port)
        client.subscribe(self.command_topic, qos=1)
        client.subscribe(self.nav_topic, qos=1)

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties) -> None:
        logger.warning("MQTT disconnected (rc=%s) — will reconnect", reason_code)

    def _on_message(self, client, userdata, msg) -> None:
        # Dispatch to the thread pool immediately so the paho network loop
        # thread is never blocked — blocking it prevents keepalive ping/pong
        # and causes the broker to kill the connection silently.
        payload = msg.payload  # capture before the paho buffer might be reused
        topic = msg.topic
        self._cmd_executor.submit(self._handle_message, topic, payload)

    def _handle_message(self, topic: str, payload: bytes) -> None:
        if topic == self.nav_topic:
            cid = None
            try:
                data = json.loads(payload)
                url = data.get("url", "")
                cid = data.get("command_id")
                if url:
                    self._stop_playlist()
                    navigate(url)
                    _report_command(f"navigate: {url}", True, command_id=cid)
                else:
                    _report_command("navigate", False, "Empty URL", command_id=cid)
            except Exception as exc:
                logger.error("Nav message parse error: %s", exc)
                _report_command("navigate", False, str(exc), command_id=cid)
        else:
            handle_command(payload)

    # --- Main loop ---

    def run(self) -> None:
        if self.mqtt_host:
            self.client.connect_async(self.mqtt_host, self.mqtt_port, keepalive=30)
            self.client.loop_start()
        else:
            logger.warning("No MQTT host configured — commands disabled")

        self._sync_hosts()
        self._sync_browser_flags()
        # Pull node settings on every restart, applying heartbeat/jitter/metadata
        # cadence and reporting success/failure to the event log.
        self._apply_settings(report=True)
        # Resume any active playlist before the first heartbeat so the DB's
        # playlist_state (written by the previous run) is still readable here.
        self._resume_state()
        # Send initial heartbeat with all data, then the loop handles subsequent ones.
        # Features are NOT pushed here — they're admin-authoritative and only change
        # via explicit detection or detected display drift.
        self._post_heartbeat(include_metadata=True)
        # Re-detect capabilities only if the connected display has changed since last run.
        self._check_display_drift()
        _report_command("agent_restart", True)
        hb_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        hb_thread.start()
        settings_thread = threading.Thread(target=self._settings_loop, daemon=True)
        settings_thread.start()
        input_thread = threading.Thread(target=self._input_monitor_loop, daemon=True)
        input_thread.start()

        logger.info("kio agent running (kiosk_id=%s)", self.kiosk_id)
        try:
            self._stop.wait()
        except KeyboardInterrupt:
            pass
        finally:
            self._stop.set()
            self._post_heartbeat(online=False)
            self._cmd_executor.shutdown(wait=False)
            if self.mqtt_host:
                self.client.loop_stop()
                self.client.disconnect()
            logger.info("kio agent stopped")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cfg = load_config()
    TLS_VERIFY = cfg["tls_verify"]
    if not TLS_VERIFY:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        logger.warning("TLS verification disabled — all API requests will skip cert checks")
    logger.info("Loaded config from %s — will communicate with API at %s", CONFIG_FILE, cfg["api_url"])
    # Resolve the node id from the API via the token (so config need not carry it).
    cfg["kiosk_id"] = resolve_kiosk_id(cfg)
    logger.info(
        "kio agent starting — version=%s boot_id=%s kiosk_id=%s config=%s api=%s tls=%s mqtt=%s:%s topic=%s features=%s",
        AGENT_VERSION,
        BOOT_ID,
        cfg["kiosk_id"],
        CONFIG_FILE,
        cfg["api_url"],
        "on" if TLS_VERIFY else "OFF",
        cfg["mqtt_host"],
        cfg["mqtt_port"],
        cfg["topic_prefix"],
        ",".join(cfg["features"]) or "none",
    )
    _agent = KioAgent(cfg)
    _agent.run()
