"""Configuration loading and on-device persistence.

Reads the node config (``kiosk.yaml``), resolves the kiosk id from the API, and
persists the various small state files the agent keeps between restarts: features,
hardware state + display fingerprint, cached settings, and the per-API-URL comms
history. Persistence is best-effort and reports permission errors via
:mod:`kio_agent.reporting`.
"""

import glob
import hashlib
import json
import time
from datetime import datetime, timezone

import requests
import yaml

from kio_agent import runtime
from kio_agent.constants import (
    COMMS_FILE,
    CONFIG_FILE,
    SETTINGS_FILE,
    STATE_FILE,
    logger,
)
from kio_agent.reporting import _report_file_error
from kio_agent.runtime import AGENT_VERSION, BOOT_ID

# ---------------------------------------------------------------------------
# Features
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


# ---------------------------------------------------------------------------
# Hardware state + display fingerprint
# ---------------------------------------------------------------------------


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


def _report_comms_state() -> None:
    """Upload the on-device comms-state file to the API as node meta on demand.

    Stored under the `comms_state` meta key so the dashboard's debug view can pull
    it back. `reported_at` lets the dashboard tell a fresh upload from a stale one,
    and `current_api_url` flags which of the per-URL records is the active server.
    """
    if not runtime.agent:
        return
    records = _load_comms_state()
    payload = {
        "reported_at": datetime.now(timezone.utc).isoformat(),
        "current_api_url": runtime.agent.api_url,
        "heartbeat_interval_seconds": runtime.agent._hb_interval,
        "heartbeat_jitter_seconds": runtime.agent._hb_jitter,
        "records": records,
    }
    try:
        requests.put(
            f"{runtime.agent.api_url}/agent/meta/comms_state",
            json={"value": payload},
            headers={"Authorization": f"Bearer {runtime.agent.api_token}"},
            timeout=10,
            verify=runtime.TLS_VERIFY,
        )
        logger.info("Reported comms state (%d server record(s))", len(records))
    except Exception as exc:
        logger.warning("Failed to report comms state: %s", exc)


# ---------------------------------------------------------------------------
# Settings cache
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Config file + kiosk id resolution
# ---------------------------------------------------------------------------


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
        "kiosk_id": cfg.get("id") or "",
        "api_url": api["url"].rstrip("/"),
        "api_token": api["token"],
        "tls_verify": api.get("tls_verify", True),
        "mqtt_host": mqtt_cfg.get("host", ""),
        "mqtt_port": int(mqtt_cfg.get("port", 1883)),
        "topic_prefix": mqtt_cfg.get("topic_prefix", "kio/prd"),
        "features": raw_features,
        "start_url": cfg.get("start_url") or "about:blank",
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
                # Use the resolved TLS_VERIFY (system CA bundle) like every other
                # request — NOT the raw cfg["tls_verify"]. The raw value is True by
                # default, which makes requests fall back to certifi's bundle, and
                # certifi never sees the internal CA that update-ca-certificates adds.
                timeout=10,
                verify=runtime.TLS_VERIFY,
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
