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
COMMS_FILE = "/etc/kio/comms-state.json"
CDP_BASE = "http://localhost:9222"
_agent: "KioAgent | None" = None

# Resolved from config at startup; passed straight to requests' verify= (a bool,
# or a path to a CA bundle).
TLS_VERIFY: "bool | str" = True

# Debian / Raspberry Pi OS system trust store. update-ca-certificates (driven by
# sync_certs) maintains it, so it covers public CAs *and* any internal CA the node
# has been told to trust — which is why "verify on" defaults here rather than to
# the bundled certifi list (certifi never sees update-ca-certificates' additions).
_SYSTEM_CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"


def resolve_tls_verify(value: "bool | str") -> "bool | str":
    """Map config's tls_verify into a value for requests' verify= argument.

    - false / "false" / "0" / "no" / "off" -> False  (no verification; insecure)
    - any other string                      -> that path, used as a CA bundle (pinning)
    - true (the default)                    -> the system CA store if present, else
                                               certifi (returns True)
    """
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("false", "0", "no", "off"):
            return False
        if low not in ("true", "1", "yes", "on", ""):
            return value  # explicit CA bundle path
        value = True
    if not value:
        return False
    return _SYSTEM_CA_BUNDLE if os.path.exists(_SYSTEM_CA_BUNDLE) else True

def _read_version() -> str:
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        return open(os.path.join(here, "VERSION")).read().strip()
    except Exception:
        return "unknown"

AGENT_VERSION = _read_version()

# An update restarts the agent, so the agent that issues it can only log the
# attempt. A marker written before launch lets the *new* agent (post-restart)
# log the success/failure outcome on boot. See _report_update_result().
UPDATE_STATE_FILE = "/opt/kio-agent/update-state.json"
UPDATE_LOG_FILE = "/var/log/kio-agent-update.log"

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


# ---------------------------------------------------------------------------
# Comms state — per-API-URL record of when we last reached each server.
#
# Dev nodes hop between API servers, so contact history is keyed by API URL
# rather than kept as one global timestamp: switching servers must not erase
# what we knew about the previous one. Each record holds the last-contact time
# plus whatever details the caller wants to remember (resolved kiosk_id, the
# endpoint that succeeded, agent version, etc.).
# ---------------------------------------------------------------------------

def _load_comms_state() -> dict:
    try:
        with open(COMMS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_comms_state(state: dict) -> None:
    try:
        with open(COMMS_FILE, "w") as f:
            json.dump(state, f, indent=2, sort_keys=True)
    except PermissionError:
        logger.warning("Permission denied writing %s", COMMS_FILE)
        _report_file_error(COMMS_FILE)
    except Exception as exc:
        logger.warning("Failed to persist comms state: %s", exc)


def record_api_contact(api_url: str, **details) -> None:
    """Stamp a successful API communication for `api_url` and merge in `details`.

    Updates `last_contact_at` (ISO-8601) and `last_contact_epoch` (unix seconds)
    so anything can compute "time since last contact" later, and folds any extra
    keyword details into that server's record without dropping previously stored
    fields. Best-effort: a write failure is logged, never raised.
    """
    if not api_url:
        return
    now = datetime.now(timezone.utc)
    state = _load_comms_state()
    rec = state.get(api_url) or {}
    rec["last_contact_at"] = now.isoformat()
    rec["last_contact_epoch"] = now.timestamp()
    rec.update(details)
    state[api_url] = rec
    _save_comms_state(state)


def seconds_since_last_contact(api_url: str) -> float | None:
    """Seconds since we last reached `api_url`, or None if never recorded."""
    rec = _load_comms_state().get(api_url) or {}
    epoch = rec.get("last_contact_epoch")
    if epoch is None:
        return None
    return max(0.0, datetime.now(timezone.utc).timestamp() - float(epoch))


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
                    record_api_contact(
                        cfg["api_url"],
                        last_event="resolve_kiosk_id",
                        kiosk_id=kid,
                        agent_version=AGENT_VERSION,
                        boot_id=BOOT_ID,
                    )
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
            # responseStatus is the HTTP status of the main-document navigation
            # (Chromium >=109); 0/undefined for about:blank, cached, or failed loads,
            # which we collapse to null so the dashboard can omit the badge.
            "expression": "({age: Math.round((Date.now() - performance.timeOrigin) / 1000),"
                          " active: document.visibilityState === 'visible',"
                          " status: ((performance.getEntriesByType('navigation')[0] || {}).responseStatus) || null})",
            "returnByValue": True,
        })
        val = (((r or {}).get("result") or {}).get("result") or {}).get("value") or {}
        age = val.get("age")
        status = val.get("status")
        return {"age_seconds": int(age) if age is not None else None,
                "active": bool(val.get("active")),
                "http_status": int(status) if status else None}
    except Exception:
        return {"age_seconds": None, "active": False, "http_status": None}


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


# Only these URL schemes may be loaded in the kiosk browser. Blocks
# javascript:, data:, file:, chrome: etc. that could be injected via an MQTT
# navigate command to run code or read local files in the page context.
_ALLOWED_URL_SCHEMES = ("http://", "https://", "about:")


def is_safe_url(url: str) -> bool:
    return isinstance(url, str) and url.strip().lower().startswith(_ALLOWED_URL_SCHEMES)


def navigate(url: str) -> None:
    if not is_safe_url(url):
        logger.warning("navigate: rejected disallowed URL scheme: %r", url)
        raise ValueError(f"disallowed URL scheme: {url!r}")
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
# Tab cycler
# ---------------------------------------------------------------------------

class TabCycler:
    """Rotates focus through the node's currently-open browser tabs on a timer.

    Unlike PlaylistPlayer this never opens, preloads, or closes tabs — it only
    activates whatever tabs already exist, so newly opened or closed tabs are
    picked up automatically on the next tick. Tabs are visited in the operator's
    saved order (tab_order, a list of URLs); tabs whose URL isn't in that list
    are appended in CDP order. The rotation advances from whichever tab is
    currently on-screen, so a manual Focus simply shifts where the next hop lands.
    """

    def __init__(self, interval_seconds: int, tab_order: list[str] | None = None,
                 on_rotate=None) -> None:
        self._interval = max(1, int(interval_seconds))
        self._tab_order = [u for u in (tab_order or []) if isinstance(u, str)]
        self._started_at = time.time()
        self._current_tab_id: str | None = None
        # Called after each rotation so the agent can push a heartbeat immediately,
        # keeping the dashboard's on-screen-tab highlight in sync with the rotation
        # instead of lagging until the next routine heartbeat.
        self._on_rotate = on_rotate
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=2)

    def _ordered_tabs(self, tabs: list[dict]) -> list[dict]:
        """Order live tabs by the saved URL order; unknown URLs keep CDP order at the end."""
        if not self._tab_order:
            return tabs
        rank = {url: i for i, url in enumerate(self._tab_order)}
        return sorted(tabs, key=lambda t: rank.get(t.get("url", ""), len(rank)))

    def _run(self) -> None:
        while not self._stop_event.wait(self._interval):
            tabs = self._ordered_tabs(_get_tabs())
            if not tabs:
                continue
            # Advance from the tab that's currently on-screen (falling back to the
            # one we last activated), so a manual Focus mid-cycle is respected.
            cur = next((i for i, t in enumerate(tabs) if t.get("active")), None)
            if cur is None:
                cur = next((i for i, t in enumerate(tabs) if t["id"] == self._current_tab_id), -1)
            nxt = tabs[(cur + 1) % len(tabs)]
            if _activate_tab(nxt["id"]):
                self._current_tab_id = nxt["id"]
                if self._on_rotate is not None:
                    try:
                        self._on_rotate()
                    except Exception as exc:
                        logger.debug("tab cycle on_rotate hook failed: %s", exc)

    def current_state(self) -> dict:
        return {
            "interval_seconds": self._interval,
            "current_tab_id": self._current_tab_id,
            "started_at": datetime.fromtimestamp(
                self._started_at, tz=timezone.utc
            ).isoformat(),
        }


# ---------------------------------------------------------------------------
# Command handler
# ---------------------------------------------------------------------------

# DDC/CI-backed capabilities and the VCP code each is probed with.
_KNOWN_VCP_CAPS = [
    ("display_power", "D6"),  # power mode
    ("input_switch", "60"),   # input source
    ("brightness", "10"),     # luminance
]


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
            info = {"cmd": f"ddcutil getvcp {code}", "returncode": r.returncode,
                    "stdout": r.stdout.strip()[:1000], "stderr": r.stderr.strip()[:500],
                    "attempts": attempt}
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
                (l.split(":", 1)[1].strip() for l in r.stdout.splitlines() if "Physical Address" in l),
                "unknown",
            )
            info = {"cmd": " ".join(cec_cmd), "returncode": r.returncode,
                    "stdout": r.stdout.strip()[:1000], "stderr": r.stderr.strip()[:500],
                    "physical_address": physical, "attempts": attempt}
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

    # Display modes (wlr-randr)
    display_modes, primary_output = _detect_display_modes()
    if display_modes:
        info["display_modes"] = display_modes
    if primary_output:
        info["primary_output"] = primary_output

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


def _report_comms_state() -> None:
    """Upload the on-device comms-state file to the API as node meta on demand.

    Stored under the `comms_state` meta key so the dashboard's debug view can pull
    it back. `reported_at` lets the dashboard tell a fresh upload from a stale one,
    and `current_api_url` flags which of the per-URL records is the active server.
    """
    if not _agent:
        return
    records = _load_comms_state()
    payload = {
        "reported_at": datetime.now(timezone.utc).isoformat(),
        "current_api_url": _agent.api_url,
        "heartbeat_interval_seconds": _agent._hb_interval,
        "heartbeat_jitter_seconds": _agent._hb_jitter,
        "records": records,
    }
    try:
        requests.put(
            f"{_agent.api_url}/agent/meta/comms_state",
            json={"value": payload},
            headers={"Authorization": f"Bearer {_agent.api_token}"},
            timeout=10,
            verify=TLS_VERIFY,
        )
        logger.info("Reported comms state (%d server record(s))", len(records))
    except Exception as exc:
        logger.warning("Failed to report comms state: %s", exc)


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
    blocks = [f'profile kiosk_dual {{\n{dual}\n}}']
    if others:
        blocks.append(f'profile kiosk_solo {{\n{target_line}\n}}')
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
            ["kanshi"], env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
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
                        m = re.match(r'\s+(\d+x\d+)\s+px,\s+([\d.]+)\s+Hz(.*)', line)
                        if m:
                            mode_str, rate_str, flags = m.group(1), m.group(2), m.group(3)
                            modes[current_output].append({
                                "mode": mode_str,
                                "rate": round(float(rate_str), 3),
                                "current": "current" in flags,
                                "preferred": "preferred" in flags,
                            })
                        else:
                            pm = re.match(r'\s+Position:\s*(\d+),\s*(\d+)', line)
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
            import re as _re
            output_name = _re.sub(r'^card\d+-', '', os.path.basename(output_dir))
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
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode == 0:
        logger.info("Display %s via ddcutil VCP D6=%s", "on" if on else "off", value)
    else:
        logger.warning("Display %s failed: wlopm, CEC, and ddcutil all failed", "on" if on else "off")


def _set_brightness(value: int) -> bool:
    """Set display luminance via DDC/CI VCP 10 (0–100). Returns True on success.

    DDC/CI only — unlike power there is no CEC/wlopm fallback, because neither has
    a luminance command. A node whose display lacks DDC/CI never advertises the
    brightness capability, so this is reached only on capable hardware.
    """
    value = max(0, min(100, int(value)))
    r = subprocess.run(
        ["ddcutil", "setvcp", "10", str(value)],
        capture_output=True, text=True, timeout=10,
    )
    if r.returncode == 0:
        logger.info("Brightness set to %d via ddcutil VCP 10", value)
        return True
    logger.warning("Brightness set failed (exit %d): %s", r.returncode, r.stderr.strip())
    return False


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


def _clear_update_marker() -> None:
    try:
        os.remove(UPDATE_STATE_FILE)
    except Exception:
        pass


def _report_update_result() -> None:
    """After an update, log its outcome — and reboot to fully apply it.

    The update_agent handler leaves a marker before the self-update restarts the
    agent. This runs in two phases across that reboot:
      1. First boot after the reinstall: confirm the version advanced, log
         "update_agent_rebooting", flag the marker, and reboot (so kernel-cmdline /
         group changes from setup.sh actually take effect).
      2. Boot after the reboot: the marker's reboot_pending flag tells us to report
         update_agent_success and clear the marker.
    A failed update reports update_agent_failure and does NOT reboot.
    """
    if not _agent:
        return
    try:
        if not os.path.exists(UPDATE_STATE_FILE):
            return
        try:
            with open(UPDATE_STATE_FILE) as f:
                marker = json.load(f)
        except Exception:
            marker = {}

        ref = marker.get("ref") or "?"
        from_version = marker.get("from_version")
        to_version = AGENT_VERSION

        # Phase 2 — already rebooted for this update: report success and finish.
        if marker.get("reboot_pending"):
            _report_command(
                "update_agent_success", True,
                f"Updated {from_version or '?'} -> {to_version} (ref {ref}) and rebooted",
            )
            _clear_update_marker()
            return

        # Phase 1 — first boot after the reinstall. Decide success vs failure.
        changed = bool(from_version) and from_version != to_version
        tail = ""
        if os.path.exists(UPDATE_LOG_FILE):
            try:
                with open(UPDATE_LOG_FILE, errors="replace") as f:
                    tail = f.read()[-400:].strip().replace("\n", " | ")
            except Exception:
                tail = ""

        if not (changed or "RESULT: ok" in tail):
            msg = f"Update to ref {ref} did not change version (still {to_version})"
            if tail:
                msg = f"{msg}: {tail[-200:]}"
            _report_command("update_agent_failure", False, msg)
            _clear_update_marker()
            return

        # Success — flag the marker so the post-reboot boot reports success, then
        # reboot. Persist the flag BEFORE rebooting so a failed write can't loop.
        marker["reboot_pending"] = True
        try:
            with open(UPDATE_STATE_FILE, "w") as f:
                json.dump(marker, f)
        except Exception as exc:
            logger.warning("update: could not set reboot_pending (%s); reporting success without reboot", exc)
            _report_command(
                "update_agent_success", True,
                f"Updated {from_version or '?'} -> {to_version} (ref {ref})",
            )
            _clear_update_marker()
            return

        _report_command(
            "update_agent_rebooting", True,
            f"Rebooting for update {from_version or '?'} -> {to_version} (ref {ref})",
        )
        logger.info("Rebooting to apply update %s -> %s", from_version, to_version)
        subprocess.run(["sudo", "reboot"], check=False)
    except Exception as exc:
        logger.warning("Failed to report update result: %s", exc)


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
        elif command == "start_tab_cycle":
            interval = int(cmd.get("interval_seconds", 15))
            tab_order = cmd.get("tab_order", []) or []
            if _agent:
                _agent._start_tab_cycle(interval, tab_order=tab_order)
            else:
                logger.warning("start_tab_cycle: agent not ready")
        elif command == "stop_tab_cycle":
            if _agent:
                _agent._stop_tab_cycle()
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
                    _agent._stop_tab_cycle()
                    default_url = _agent.default_url
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
                # Focusing a tab is a manual takeover — stop any running playlist or
                # tab cycle so it doesn't rotate away from the tab the operator just
                # selected.
                if _agent:
                    _agent._stop_playlist()
                    _agent._stop_tab_cycle()
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
            if url and not is_safe_url(url):
                logger.warning("navigate_tab: rejected disallowed URL scheme: %r", url)
                _report_command("navigate_tab", False, f"Disallowed URL scheme: {url}", command_id=command_id)
                return
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
        elif command == "sync_certs":
            if _agent:
                # Reports its own success/error event (incl. malformed-cert detection),
                # so return here rather than falling through to the generic ack below.
                _agent._sync_certs(command_id=command_id)
            else:
                logger.warning("sync_certs: agent not ready")
                _report_command("sync_certs", False, "agent not ready", command_id=command_id)
            return
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
        elif command == "report_comms_state":
            _report_comms_state()
        elif command == "reload":
            reload_page()
        elif command == "reboot":
            _report_command("reboot", True, command_id=command_id)
            subprocess.run(["sudo", "reboot"], check=False)
            return
        elif command == "update_agent":
            # The API dictates which git ref to update to (its own release tag, or
            # main in dev) so the node lands on a build compatible with the server.
            # The ref travels via a file because the sudoers entry is an exact,
            # no-argument match on /opt/kio-agent/self-update.
            ref = (cmd.get("ref") or "main").strip()
            try:
                with open("/opt/kio-agent/update-ref", "w") as f:
                    f.write(ref)
            except Exception as exc:
                logger.warning("update_agent: could not write update-ref (%s); defaulting to main", exc)
            # Drop a marker so the new agent (after the restart this triggers) can log
            # update_agent_success / update_agent_failure once it comes back.
            try:
                with open(UPDATE_STATE_FILE, "w") as f:
                    json.dump({
                        "ref": ref,
                        "from_version": AGENT_VERSION,
                        "issued_at": datetime.now(timezone.utc).isoformat(),
                    }, f)
            except Exception as exc:
                logger.warning("update_agent: could not write update-state marker: %s", exc)
            # Launch detached — self-update re-execs into its own systemd unit so the
            # kio-agent restart at the end of the update can't kill it mid-flight.
            subprocess.Popen(
                ["sudo", "/opt/kio-agent/self-update"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            _report_command("update_agent_attempt", True, f"Update started (ref {ref})", command_id=command_id)
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
        elif command == "set_resolution":
            output = cmd.get("output", "")
            mode = cmd.get("mode", "")
            rate = cmd.get("rate")
            if not output or not mode:
                _report_command("set_resolution", False, "Missing output or mode", command_id=command_id)
                return
            # Write kanshi config first so the resolution persists across session
            # restarts and display reconnects even if the live apply below fails;
            # reload kanshi so its in-memory profile matches the new config.
            if _write_kanshi_config(output, mode, rate):
                _reload_kanshi()
            # Live apply for the running session, targeting the connector that is
            # actually present now (the dashboard-sent name can be a stale HDMI-A-N).
            connector = _current_connector(output)
            args = ["sudo", "/opt/kio-agent/set-resolution", connector, mode]
            if rate is not None:
                args.append(str(rate))
            logger.info("set_resolution: running %s", " ".join(args))
            r = subprocess.run(args, capture_output=True, text=True, timeout=15)
            if r.returncode != 0:
                err = r.stderr.strip() or r.stdout.strip() or "set-resolution failed"
                logger.warning("set_resolution failed (exit %d): %s", r.returncode, err)
                _report_command("set_resolution", False, err, command_id=command_id)
                return
            logger.info("Resolution set: %s %s @ %s", connector, mode, rate)
            _report_command(
                "set_resolution", True,
                f"{output} {mode}" + (f" @ {rate} Hz" if rate is not None else ""),
                command_id=command_id,
            )
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
        elif command == "set_brightness":
            # Gate check (defense in depth — the dashboard already hides the control
            # when the feature is disabled for this node).
            if not (_agent and _agent._brightness_enabled):
                _report_command("set_brightness", False, "Brightness feature disabled for this node",
                                command_id=command_id)
                return
            value = cmd.get("value")
            if value is None:
                _report_command("set_brightness", False, "Missing value", command_id=command_id)
                return
            if not _set_brightness(value):
                _report_command("set_brightness", False, "ddcutil setvcp 10 failed", command_id=command_id)
                return
            _agent._current_brightness = max(0, min(100, int(value)))
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
        # The page shown when the node has nothing else to do (boot with no playlist,
        # last tab closed). Seeded from the local start_url; the global default page
        # (Settings → Default Page) overrides it once settings are fetched.
        self.default_url:  str       = self.start_url
        self.command_topic = f"{self.topic_prefix}/kiosks/{self.kiosk_id}/command"
        self.nav_topic     = f"{self.topic_prefix}/kiosks/{self.kiosk_id}/nav"
        self._stop = threading.Event()
        self._player: PlaylistPlayer | None = None
        self._cycler: TabCycler | None = None
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
        # Brightness feature gate + default luminance, delivered per node via
        # GET /agent/settings and refreshed live on sync_settings/checkin. Seeded
        # off so the feature stays dark until the gate is enabled for this node.
        self._brightness_enabled = False
        self._brightness_default = 80
        self._current_brightness: int | None = None  # last value we applied

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
            # No playlist — reopen whatever tabs the node had before the reboot,
            # falling back to the default page if there were none worth restoring.
            if self._restore_tabs(state.get("tabs") or []):
                return
            logger.info("Boot resume: no active playlist or saved tabs to resume")
            self._show_default_page()
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

    def _restore_tabs(self, tabs: list[dict]) -> bool:
        """Reopen the tabs the node had open before its last reboot.

        browser-start has already launched Chromium on the start_url (one tab), so
        we reuse that tab for the first saved URL, open the rest as background tabs,
        then refocus whichever tab was active before the reboot — leaving the node
        with exactly the set of pages it had open. Returns True if any tab was
        restored, False when there was nothing worth restoring (idle/default page).
        """
        restorable = [
            t for t in tabs
            if t.get("url") and is_safe_url(t["url"]) and not t["url"].startswith("about:")
        ]
        if not restorable:
            return False

        if not _wait_for_chromium():
            logger.warning("Boot resume: Chromium not ready, skipping tab restore")
            return False

        logger.info("Boot resume: restoring %d tab(s) open before reboot", len(restorable))
        active_url = next((t["url"] for t in restorable if t.get("active")), restorable[0]["url"])

        # Reuse the tab browser-start already opened for the first URL; open the rest.
        ids_by_url: dict[str, str] = {}
        navigate(restorable[0]["url"])
        first = _get_tab()
        if first:
            ids_by_url[restorable[0]["url"]] = first["id"]
        for t in restorable[1:]:
            opened = _open_tab(t["url"])
            if opened:
                ids_by_url[t["url"]] = opened["id"]

        # Restore focus to whichever tab was active before the reboot.
        active_id = ids_by_url.get(active_url)
        if active_id:
            try:
                requests.get(f"{CDP_BASE}/json/activate/{active_id}", timeout=5)
            except Exception as exc:
                logger.warning("Boot resume: failed to focus restored tab: %s", exc)
        return True

    def _show_default_page(self) -> None:
        """Show the global default page when the node is idle at boot.

        browser-start already opened the local start_url, so we only override when a
        global default page (Settings → Default Page) is set and points somewhere
        else. Waits for Chromium so the navigate lands instead of racing the launch.
        """
        url = self.default_url
        if not url or url in ("about:blank", self.start_url):
            return  # keep whatever browser-start already opened
        if not _wait_for_chromium():
            logger.warning("Default page: Chromium not ready, skipping idle navigate to %s", url)
            return
        logger.info("Idle at boot — loading default page %s", url)
        navigate(url)

    def _stop_playlist(self) -> None:
        if self._player is not None:
            self._player.stop()
            self._player = None

    def _start_playlist(self, playlist_id: str, items: list[dict], playlist_name: str = "",
                        start_idx: int = 0, refresh_seconds: int = PLAYLIST_REFRESH_SECONDS) -> None:
        self._stop_playlist()
        # A playlist takes over tab rotation, so stop any manual tab cycle first.
        self._stop_tab_cycle()
        self._player = PlaylistPlayer(playlist_id, items, playlist_name=playlist_name,
                                      start_idx=start_idx, refresh_seconds=refresh_seconds)
        self._player.start()

    def _stop_tab_cycle(self) -> None:
        if self._cycler is not None:
            self._cycler.stop()
            self._cycler = None

    def _start_tab_cycle(self, interval_seconds: int, tab_order: list[str] | None = None) -> None:
        self._stop_tab_cycle()
        # Cycling and a playlist both drive tab focus — they're mutually exclusive.
        self._stop_playlist()
        # Push a heartbeat after each rotation so the dashboard reflects the focused
        # tab promptly instead of waiting for the next routine (~30s) heartbeat.
        self._cycler = TabCycler(interval_seconds, tab_order=tab_order,
                                 on_rotate=lambda: self._post_heartbeat())
        self._cycler.start()
        logger.info("Tab cycle started: every %ss over %d ordered urls",
                    interval_seconds, len(tab_order or []))

    # --- HTTP heartbeat ---

    def _sync_certs(self, command_id: str | None = None) -> None:
        import glob
        import re
        try:
            resp = requests.get(
                f"{self.api_url}/agent/certs",
                headers={"Authorization": f"Bearer {self.api_token}"},
                timeout=30,
                verify=TLS_VERIFY,
            )
            if resp.status_code != 200:
                msg = f"Failed to fetch certs: HTTP {resp.status_code}"
                logger.warning(msg)
                _report_command("sync_certs", False, msg, command_id=command_id)
                return
            certs = resp.json()
            cert_dir = "/etc/kio/certs"
            os.makedirs(cert_dir, exist_ok=True)
            for f in glob.glob(f"{cert_dir}/*.crt"):
                os.remove(f)
            # Validate each PEM before installing — update-ca-certificates silently
            # skips undecodable certs and still exits 0, so a bad paste would otherwise
            # report a false success. Surface the bad ones as an event-log error.
            invalid = []
            for cert in certs:
                safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", cert["name"])
                path = f"{cert_dir}/{safe_name}.crt"
                with open(path, "w") as f:
                    f.write(cert["content"])
                check = subprocess.run(
                    ["openssl", "x509", "-noout", "-in", path],
                    capture_output=True, text=True, timeout=10,
                )
                if check.returncode != 0:
                    invalid.append(cert["name"])
                    os.remove(path)  # don't hand a malformed file to update-ca-certificates
            result = subprocess.run(
                ["sudo", "/opt/kio-agent/update-certs"],
                capture_output=True, text=True, timeout=30,
            )
            installed = len(certs) - len(invalid)
            if result.returncode == 0:
                # update-ca-certificates succeeded (even if some pasted certs were
                # invalid and skipped) — the trust store was refreshed, so stamp it.
                record_api_contact(
                    self.api_url,
                    last_event="sync_certs",
                    certs_synced_at=datetime.now(timezone.utc).isoformat(),
                )
            if result.returncode != 0:
                err = result.stderr.strip() or "update-certs failed"
                logger.warning("update-certs failed: %s", err)
                _report_command("sync_certs", False, err, command_id=command_id)
            elif invalid:
                msg = f"{installed} installed; {len(invalid)} failed to parse: {', '.join(invalid)}"
                logger.warning("Cert sync partial: %s", msg)
                _report_command("sync_certs", False, msg, command_id=command_id)
            else:
                logger.info("Certs synced: %d installed", installed)
                _report_command("sync_certs", True, f"{installed} installed", command_id=command_id)
        except PermissionError as exc:
            logger.warning("Permission denied writing certs: %s", exc)
            _report_file_error("/etc/kio/certs")
            _report_command("sync_certs", False, f"permission denied: {exc}", command_id=command_id)
        except Exception as exc:
            logger.warning("Cert sync failed: %s", exc)
            _report_command("sync_certs", False, str(exc), command_id=command_id)

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
                record_api_contact(
                    self.api_url,
                    last_event="sync_hosts",
                    hosts_synced_at=datetime.now(timezone.utc).isoformat(),
                )
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
                    _restart_browser()
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
        """Read display power state from the most reliable source for the hardware.

        Order matters and was the source of a real bug: querying CEC first broke
        DDC/CI monitors (e.g. Dell S2721QS) that have no CEC TV to answer — the
        give-device-power-status query to a non-existent TV returned a value that
        parsed as "off" while the panel was on. So:

          1. DDC/CI VCP D6 — the monitor's own power register, authoritative when
             present (sl=0x01 on; 0x04/0x05 DPMS standby/off). Most kio nodes
             drive a DDC monitor, and a real TV simply doesn't answer DDC, so this
             only "wins" when it's the right source.
          2. CEC give-device-power-status — for HDMI-CEC *TVs* without DDC. Only
             trusted on a genuine reply (returncode 0 *and* a pwr-state line); a
             monitor with no CEC TV NAKs the query, which must NOT read as "off".
          3. wlopm — compositor output only (always "on" under labwc), last resort.
        """
        import re
        # 1. DDC/CI power mode (D6). Authoritative for DDC monitors.
        try:
            r = subprocess.run(
                ["ddcutil", "getvcp", "D6"],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0:
                m = re.search(r'sl=0x([0-9a-fA-F]+)', r.stdout)
                if m:
                    return int(m.group(1), 16) == 1
        except Exception as exc:
            logger.debug("ddcutil getvcp D6 failed: %s", exc)
        # 2. CEC — only a real TV reply counts (guard returncode; ignore NAKs).
        if os.path.exists("/dev/cec0"):
            try:
                r = subprocess.run(
                    ["sudo", "cec-ctl", "-d", "/dev/cec0", "--playback", "-t", "0", "--give-device-power-status"],
                    capture_output=True, text=True, timeout=10,
                )
                if r.returncode == 0:
                    for line in r.stdout.splitlines():
                        low = line.lower()
                        if "pwr-state" not in low:
                            continue
                        # e.g. "pwr-state: on" / "standby" / "in transition standby to on"
                        if "to on" in low or ": on" in low:
                            return True
                        if "standby" in low:
                            return False
            except Exception as exc:
                logger.debug("cec power status failed: %s", exc)
        # 3. Wayland compositor output: always True on running labwc; last resort.
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

    def _get_uptime_seconds(self) -> int | None:
        """System uptime in whole seconds from /proc/uptime, or None if unreadable.
        Reported on the metadata heartbeat (and on boot); the dashboard extrapolates
        the live value from this plus the time since it was reported."""
        try:
            with open("/proc/uptime") as f:
                return int(float(f.read().split()[0]))
        except Exception:
            return None

    def _effective_features(self) -> list[str]:
        """Features to advertise to the dashboard: detected hardware capabilities,
        minus any that are gated off. `brightness` hardware support is real but only
        exposed while the brightness_enabled gate is on, so the dashboard slider
        appears/disappears with the gate without any UI-side flag lookup."""
        feats = self.features
        if not self._brightness_enabled and "brightness" in feats:
            feats = [f for f in feats if f != "brightness"]
        return feats

    def _post_heartbeat(self, online: bool = True, include_metadata: bool = False,
                        include_features: bool = False) -> None:
        # Hardware state (ddcutil/CEC) is slow — only poll on the hourly metadata
        # heartbeat so routine 30s ticks stay fast and don't block tab/URL updates.
        payload: dict = {
            "online":             online,
            "agent_version":      AGENT_VERSION,
            "boot_id":            BOOT_ID,
            "current_url":        get_current_url() if online else None,
            "browser_tabs":       _get_tabs() if online else [],
            "playlist_state":     self._player.current_state() if self._player is not None else None,
            "tab_cycle_state":    self._cycler.current_state() if self._cycler is not None else None,
            "reporting_api_url":  self.api_url,
        }
        if include_metadata or not online:
            payload["current_input"] = self._get_current_input() if online else None
            payload["display_on"]    = self._get_display_on()    if online else False
        # Features are admin-authoritative: only reported when we have a deliberate
        # reason to update them (explicit detect, or detected display drift), never
        # on routine heartbeats — otherwise they'd clobber dashboard edits hourly.
        if include_features:
            payload["features"] = self._effective_features()
        if include_metadata:
            payload["device_type"]    = self._get_device_type()
            payload["ip_address"]     = self._get_ip_address()
            payload["uptime_seconds"] = self._get_uptime_seconds()
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
                gap = seconds_since_last_contact(self.api_url)
                record_api_contact(
                    self.api_url,
                    last_event="heartbeat",
                    kiosk_id=self.kiosk_id,
                    agent_version=AGENT_VERSION,
                    boot_id=BOOT_ID,
                )
                if gap is not None:
                    logger.info("Heartbeat OK (%.0fs since last contact)", gap)
                else:
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
        # Non-destructive merge: a capability that probed "unknown" (transient i2c
        # failure rather than a definitive "unsupported") must not be dropped if the
        # node already had it. This stops a flaky detect from silently wiping a
        # working feature (e.g. input_switch). Only a definitive "unsupported" removes.
        prior = set(self.features)
        merged = set(caps)
        for cap, info in probes.items():
            if info.get("status") == "unknown" and cap in prior:
                merged.add(cap)
        caps = sorted(merged)
        hw_info = collect_hardware_info()
        self.features = caps
        save_features(caps)
        _report_hardware_info(hw_info)
        _report_detect_log(caps, probes, hw_info)
        self._post_heartbeat(include_metadata=True, include_features=True)
        state = _load_hw_state()
        state["display_fingerprint"] = _display_fingerprint()
        _save_hw_state(state)
        record_api_contact(
            self.api_url,
            last_event="detect_capabilities",
            hardware_detect_at=datetime.now(timezone.utc).isoformat(),
        )
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
        # Global default page overrides the local start_url when set; falls back to it otherwise.
        self.default_url = s.get("default_url") or self.start_url
        logger.info(
            "Applied settings from %s: heartbeat=%ds jitter=%ds metadata=%ds checkin=%ds",
            source, self._hb_interval, self._hb_jitter, self._metadata_interval, self._settings_checkin,
        )

        # Brightness feature gate + default. Pulled here so a gate flip (global or
        # per-node) reaches the node live via sync_settings, not just on reboot.
        prev_enabled = self._brightness_enabled
        prev_default = self._brightness_default
        self._brightness_enabled = bool(int(s.get("brightness_enabled", 0)))
        self._brightness_default = max(0, min(100, int(s.get("brightness_default", self._brightness_default))))
        gate_changed = self._brightness_enabled != prev_enabled
        if self._brightness_enabled and "brightness" in self.features:
            # Apply the configured default when the gate turns on or the default
            # itself changes — but NOT on every checkin, which would clobber a
            # manual slider change between checkins.
            if gate_changed or self._brightness_default != prev_default:
                if _set_brightness(self._brightness_default):
                    self._current_brightness = self._brightness_default
        if gate_changed:
            # Re-advertise features so the dashboard shows/hides the slider live
            # (the effective feature list reflects the gate — see _effective_features).
            self._post_heartbeat(include_features=True)

        res = s.get("display_resolution")
        if res and isinstance(res, dict) and res.get("output") and res.get("mode"):
            # Keep the kanshi config in sync with NodeMeta so the compositor
            # re-applies the correct resolution on every session start and display
            # reconnect — this is the durable persistence path. Reload kanshi only
            # when the config actually changed, to avoid churn on every checkin.
            if _write_kanshi_config(res["output"], res["mode"], res.get("rate")):
                _reload_kanshi()
            # Best-effort live apply for the running session; fails silently if
            # Wayland is not up yet (kanshi applies it on compositor start). Target
            # the connector present now, since the stored name can be stale.
            connector = _current_connector(res["output"])
            args = ["sudo", "/opt/kio-agent/set-resolution", connector, res["mode"]]
            if res.get("rate") is not None:
                args.append(str(res["rate"]))
            try:
                r = subprocess.run(args, capture_output=True, text=True, timeout=15)
                if r.returncode == 0:
                    logger.info("Applied stored display resolution: %s %s @ %s", connector, res["mode"], res.get("rate"))
                else:
                    logger.warning("Live apply failed (kanshi will apply on session start): %s", r.stderr.strip())
            except Exception as exc:
                logger.warning("Live apply exception: %s", exc)
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
                    self._stop_tab_cycle()
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

        self._sync_certs()
        self._sync_hosts()
        self._sync_browser_flags()
        # Pull node settings on every restart, applying heartbeat/jitter/metadata
        # cadence and reporting success/failure to the event log.
        self._apply_settings(report=True)
        # If a self-update just ran, log update_agent_success / update_agent_failure.
        # Done after the settings sync so the detached updater has had a moment to
        # finish writing its log before we read it.
        _report_update_result()
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

        logger.info("kio agent running — version=%s kiosk_id=%s", AGENT_VERSION, self.kiosk_id)
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
    TLS_VERIFY = resolve_tls_verify(cfg["tls_verify"])
    if TLS_VERIFY is False:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        logger.warning("TLS verification disabled — all API requests will skip cert checks")
    elif isinstance(TLS_VERIFY, str):
        logger.info("TLS verification using CA bundle: %s", TLS_VERIFY)
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
