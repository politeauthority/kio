"""The :class:`KioAgent` — the agent's long-lived object and main loop.

Owns the MQTT connection (commands), the HTTP heartbeat/metadata/settings loops,
playlist and tab-cycle control, boot-time state resume, capability detection,
and the various server-driven sync operations (certs, hosts, browser flags,
settings). Module-level helpers in the sibling modules do the actual I/O; this
class wires them together and holds the runtime state.
"""

import json
import os
import random
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
import requests

from kio_agent import runtime
from kio_agent.cdp import (
    _close_tab,
    _get_tab,
    _get_tabs,
    _normalize_url,
    _open_tab,
    _wait_for_chromium,
    get_current_url,
    is_safe_url,
    navigate,
)
from kio_agent.commands import _report_update_result, handle_command
from kio_agent.config import (
    _display_fingerprint,
    _load_hw_state,
    _save_hw_state,
    load_local_settings,
    record_api_contact,
    save_features,
    save_settings,
    seconds_since_last_contact,
)
from kio_agent.constants import CDP_BASE, PLAYLIST_REFRESH_SECONDS, logger
from kio_agent.display import (
    _current_connector,
    _reload_kanshi,
    _restart_browser,
    _set_brightness,
    _wayland_env,
    _write_kanshi_config,
)
from kio_agent.hardware import collect_hardware_info, detect_capabilities
from kio_agent.playlist import PlaylistPlayer, TabCycler
from kio_agent.reporting import (
    _report_command,
    _report_detect_log,
    _report_file_error,
    _report_hardware_info,
)
from kio_agent.runtime import AGENT_VERSION, BOOT_ID


class KioAgent:
    def __init__(self, config: dict) -> None:
        self.kiosk_id: str = config["kiosk_id"]
        self.api_url: str = config["api_url"]
        self.api_token: str = config["api_token"]
        self.mqtt_host: str = config["mqtt_host"]
        self.mqtt_port: int = config["mqtt_port"]
        self.topic_prefix: str = config["topic_prefix"]
        self.features: list[str] = config["features"]
        self.start_url: str = config["start_url"]
        # The page shown when the node has nothing else to do (boot with no playlist,
        # last tab closed). Seeded from the local start_url; the global default page
        # (Settings → Default Page) overrides it once settings are fetched.
        self.default_url: str = self.start_url
        self.command_topic = f"{self.topic_prefix}/kiosks/{self.kiosk_id}/command"
        self.nav_topic = f"{self.topic_prefix}/kiosks/{self.kiosk_id}/nav"
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
        self._hb_interval = 30
        self._hb_jitter = 0
        self._metadata_interval = 3600
        self._settings_checkin = 300
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
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
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
                verify=runtime.TLS_VERIFY,
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
            playlist["name"],
            last_idx + 1,
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
        restorable = [t for t in tabs if t.get("url") and is_safe_url(t["url"]) and not t["url"].startswith("about:")]
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

    def _start_playlist(
        self,
        playlist_id: str,
        items: list[dict],
        playlist_name: str = "",
        start_idx: int = 0,
        refresh_seconds: int = PLAYLIST_REFRESH_SECONDS,
    ) -> None:
        self._stop_playlist()
        # A playlist takes over tab rotation, so stop any manual tab cycle first.
        self._stop_tab_cycle()
        self._player = PlaylistPlayer(
            playlist_id, items, playlist_name=playlist_name, start_idx=start_idx, refresh_seconds=refresh_seconds
        )
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
        self._cycler = TabCycler(interval_seconds, tab_order=tab_order, on_rotate=lambda: self._post_heartbeat())
        self._cycler.start()
        logger.info("Tab cycle started: every %ss over %d ordered urls", interval_seconds, len(tab_order or []))

    # --- HTTP heartbeat ---

    def _sync_certs(self, command_id: str | None = None) -> None:
        import glob
        import re

        try:
            resp = requests.get(
                f"{self.api_url}/agent/certs",
                headers={"Authorization": f"Bearer {self.api_token}"},
                timeout=30,
                verify=runtime.TLS_VERIFY,
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
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if check.returncode != 0:
                    invalid.append(cert["name"])
                    os.remove(path)  # don't hand a malformed file to update-ca-certificates
            result = subprocess.run(
                ["sudo", "/opt/kio-agent/update-certs"],
                capture_output=True,
                text=True,
                timeout=30,
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
                verify=runtime.TLS_VERIFY,
            )
            if resp.status_code != 200:
                return
            hosts = resp.json().get("extra_hosts", [])
            with open("/etc/kio/extra-hosts", "w") as f:
                f.write("\n".join(hosts) + "\n" if hosts else "")
            result = subprocess.run(
                ["sudo", "/opt/kio-agent/update-hosts"],
                capture_output=True,
                text=True,
                timeout=10,
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
                verify=runtime.TLS_VERIFY,
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
                capture_output=True,
                text=True,
                timeout=10,
            )
            import re

            m = re.search(r"sl=0x([0-9a-fA-F]+)", result.stdout)
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
                capture_output=True,
                text=True,
                timeout=10,
            )
            if r.returncode == 0:
                m = re.search(r"sl=0x([0-9a-fA-F]+)", r.stdout)
                if m:
                    return int(m.group(1), 16) == 1
        except Exception as exc:
            logger.debug("ddcutil getvcp D6 failed: %s", exc)
        # 2. CEC — only a real TV reply counts (guard returncode; ignore NAKs).
        if os.path.exists("/dev/cec0"):
            try:
                r = subprocess.run(
                    ["sudo", "cec-ctl", "-d", "/dev/cec0", "--playback", "-t", "0", "--give-device-power-status"],
                    capture_output=True,
                    text=True,
                    timeout=10,
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

    def _close_duplicate_tabs(self) -> int:
        """Close tabs whose page is already open in another tab, keeping one.

        For each URL open more than once, keep the active tab (else the oldest)
        and close the rest, logging each closure to the event log. Skipped while a
        playlist or tab cycle is running — those deliberately drive the tab set and
        may preload repeated content, so we must not pull tabs out from under them.
        Never closes the last remaining tab (one per URL always survives).
        """
        if self._player is not None or self._cycler is not None:
            return 0
        tabs = [t for t in _get_tabs() if (t.get("url") or "").startswith(("http://", "https://"))]
        if len(tabs) <= 1:
            return 0
        groups: dict[str, list[dict]] = {}
        for t in tabs:
            groups.setdefault(_normalize_url(t["url"]), []).append(t)
        closed = 0
        for group in groups.values():
            if len(group) < 2:
                continue
            # Keep the active tab, else the oldest; close the newer duplicates.
            group.sort(key=lambda t: (not t.get("active"), -(t.get("age_seconds") or 0)))
            for dupe in group[1:]:
                _close_tab(dupe["id"])
                closed += 1
                logger.info("Closed duplicate tab for %s", dupe["url"])
                _report_command(
                    f"close_duplicate_tab: {dupe['url']}",
                    True,
                    "Closed a duplicate tab (page already open in another tab)",
                )
        return closed

    def _post_heartbeat(
        self, online: bool = True, include_metadata: bool = False, include_features: bool = False
    ) -> None:
        # Hardware state (ddcutil/CEC) is slow — only poll on the hourly metadata
        # heartbeat so routine 30s ticks stay fast and don't block tab/URL updates.
        payload: dict = {
            "online": online,
            "agent_version": AGENT_VERSION,
            "boot_id": BOOT_ID,
            "current_url": get_current_url() if online else None,
            "browser_tabs": _get_tabs() if online else [],
            "playlist_state": self._player.current_state() if self._player is not None else None,
            "tab_cycle_state": self._cycler.current_state() if self._cycler is not None else None,
            "reporting_api_url": self.api_url,
        }
        if include_metadata or not online:
            payload["current_input"] = self._get_current_input() if online else None
            payload["display_on"] = self._get_display_on() if online else False
        # Features are admin-authoritative: only reported when we have a deliberate
        # reason to update them (explicit detect, or detected display drift), never
        # on routine heartbeats — otherwise they'd clobber dashboard edits hourly.
        if include_features:
            payload["features"] = self._effective_features()
        if include_metadata:
            payload["device_type"] = self._get_device_type()
            payload["ip_address"] = self._get_ip_address()
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
                verify=runtime.TLS_VERIFY,
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
            logger.info("Display changed (fingerprint %s -> %s) — re-detecting capabilities", last, current)
            self._run_capability_detection()

    def _fetch_settings(self) -> dict:
        """Fetch this node's effective settings from the API (raises on failure)."""
        resp = requests.get(
            f"{self.api_url}/agent/settings",
            headers={"Authorization": f"Bearer {self.api_token}"},
            timeout=10,
            verify=runtime.TLS_VERIFY,
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

        self._hb_interval = max(5, int(s.get("heartbeat_interval_seconds", self._hb_interval)))
        self._hb_jitter = max(0, int(s.get("heartbeat_jitter_seconds", self._hb_jitter)))
        self._metadata_interval = max(60, int(s.get("metadata_interval_seconds", self._metadata_interval)))
        self._settings_checkin = max(30, int(s.get("settings_checkin_seconds", self._settings_checkin)))
        # Global default page overrides the local start_url when set; falls back to it otherwise.
        self.default_url = s.get("default_url") or self.start_url
        logger.info(
            "Applied settings from %s: heartbeat=%ds jitter=%ds metadata=%ds checkin=%ds",
            source,
            self._hb_interval,
            self._hb_jitter,
            self._metadata_interval,
            self._settings_checkin,
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
                    logger.info(
                        "Applied stored display resolution: %s %s @ %s", connector, res["mode"], res.get("rate")
                    )
                else:
                    logger.warning("Live apply failed (kanshi will apply on session start): %s", r.stderr.strip())
            except Exception as exc:
                logger.warning("Live apply exception: %s", exc)
        if report:
            _report_command(
                "apply_settings",
                True,
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
            self._hb_interval,
            self._hb_jitter,
            self._metadata_interval,
            self._settings_checkin,
        )
        _report_command(
            "sync_settings",
            True,
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
            self._close_duplicate_tabs()
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
