"""Static configuration constants and the shared logger for the kio Pi agent.

Everything here is immutable and dependency-free so any module can import it
without risk of an import cycle. Mutable runtime state (agent instance, TLS
policy, resolved version) lives in :mod:`kio_agent.runtime` instead.
"""

import logging
import os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("kio-agent")

# --- On-device file paths ---
CONFIG_FILE = "/etc/kio/kiosk.yaml"
SETTINGS_FILE = "/etc/kio/settings.json"
COMMS_FILE = "/etc/kio/comms-state.json"
STATE_FILE = "/etc/kio/hardware-state.json"

# Chrome DevTools Protocol HTTP endpoint exposed by the kiosk Chromium instance.
CDP_BASE = "http://localhost:9222"

# Debian / Raspberry Pi OS system trust store. update-ca-certificates (driven by
# sync_certs) maintains it, so it covers public CAs *and* any internal CA the node
# has been told to trust — which is why "verify on" defaults here rather than to
# the bundled certifi list (certifi never sees update-ca-certificates' additions).
_SYSTEM_CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"

# An update restarts the agent, so the agent that issues it can only log the
# attempt. A marker written before launch lets the *new* agent (post-restart)
# log the success/failure outcome on boot. See reporting of the update result.
UPDATE_STATE_FILE = "/opt/kio-agent/update-state.json"
UPDATE_LOG_FILE = "/var/log/kio-agent-update.log"

# Only these URL schemes may be loaded in the kiosk browser. Blocks
# javascript:, data:, file:, chrome: etc. that could be injected via an MQTT
# navigate command to run code or read local files in the page context.
_ALLOWED_URL_SCHEMES = ("http://", "https://", "about:")

# How often each playlist tab is reloaded in the background to keep its content
# fresh. Decoupled from item duration so pages refresh on a steady cadence rather
# than reloading on every rotation. Overridable per play via the command payload.
PLAYLIST_REFRESH_SECONDS = 300

WAYLAND_ENV = {**os.environ, "WAYLAND_DISPLAY": "wayland-0"}

# DDC/CI-backed capabilities and the VCP code each is probed with.
_KNOWN_VCP_CAPS = [
    ("display_power", "D6"),  # power mode
    ("input_switch", "60"),  # input source
    ("brightness", "10"),  # luminance
]

# Installed into every preloaded tab via Page.addScriptToEvaluateOnNewDocument
# and Runtime.evaluate. Hides the page immediately, then fades it in the first
# time the tab becomes visible (visibilitychange: hidden -> visible). The guard
# prevents double-execution when both injection paths fire on the same document.
# @todo: THIS DOES NOT ACTUALLY WORK ON ANY SYSTEM
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
