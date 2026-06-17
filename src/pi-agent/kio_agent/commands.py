"""MQTT command handling.

:func:`handle_command` parses an incoming command payload and dispatches it to a
small per-command handler via :data:`_DISPATCH`. Each handler returns ``True`` to
request the generic trailing success ack, or ``False`` when it has already
reported its own result (or deliberately sends none, e.g. reboot/update). The
dispatcher owns JSON parsing, the unknown-command case, and exception reporting,
so the individual handlers stay short and focused.

Also hosts the post-update reporting (:func:`_report_update_result`) that runs on
the boot following a self-update.
"""

import json
import os
import subprocess
from datetime import datetime, timezone

import requests

from kio_agent import runtime
from kio_agent.cdp import (
    _cdp_call,
    _get_tabs,
    _open_tab,
    _reload_tab,
    get_current_url,
    is_safe_url,
    navigate,
    reload_page,
)
from kio_agent.config import _report_comms_state
from kio_agent.constants import (
    CDP_BASE,
    PLAYLIST_REFRESH_SECONDS,
    UPDATE_LOG_FILE,
    UPDATE_STATE_FILE,
    logger,
)
from kio_agent.display import (
    INPUT_MAP,
    _cec_power,
    _current_connector,
    _reload_kanshi,
    _set_brightness,
    _set_display_power,
    _write_kanshi_config,
)
from kio_agent.reporting import _report_command
from kio_agent.runtime import AGENT_VERSION

# ---------------------------------------------------------------------------
# Post-update reporting
# ---------------------------------------------------------------------------


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
    if not runtime.agent:
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
                "update_agent_success",
                True,
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
                "update_agent_success",
                True,
                f"Updated {from_version or '?'} -> {to_version} (ref {ref})",
            )
            _clear_update_marker()
            return

        _report_command(
            "update_agent_rebooting",
            True,
            f"Rebooting for update {from_version or '?'} -> {to_version} (ref {ref})",
        )
        logger.info("Rebooting to apply update %s -> %s", from_version, to_version)
        subprocess.run(["sudo", "reboot"], check=False)
    except Exception as exc:
        logger.warning("Failed to report update result: %s", exc)


# ---------------------------------------------------------------------------
# Per-command handlers
#
# Each takes the parsed command dict and the echoed command_id, and returns True
# to request the generic trailing success ack or False when it reports its own
# result (or sends none). They are dispatched by name via _DISPATCH below.
# ---------------------------------------------------------------------------


def _cmd_play_playlist(cmd: dict, command_id: str | None) -> bool:
    items = cmd.get("items", [])
    playlist_id = cmd.get("playlist_id", "unknown")
    playlist_name = cmd.get("playlist_name", "") or playlist_id
    refresh_seconds = int(cmd.get("refresh_seconds", PLAYLIST_REFRESH_SECONDS))
    if items and runtime.agent:
        runtime.agent._start_playlist(playlist_id, items, playlist_name=playlist_name, refresh_seconds=refresh_seconds)
    else:
        logger.warning("play_playlist: missing items or agent not ready")
    return True


def _cmd_stop_playlist(cmd: dict, command_id: str | None) -> bool:
    if runtime.agent:
        runtime.agent._stop_playlist()
    return True


def _cmd_sync_playlist(cmd: dict, command_id: str | None) -> bool:
    items = cmd.get("items", [])
    playlist_id = cmd.get("playlist_id", "unknown")
    playlist_name = cmd.get("playlist_name", "") or playlist_id
    refresh_seconds = int(cmd.get("refresh_seconds", PLAYLIST_REFRESH_SECONDS))
    if runtime.agent and runtime.agent._player is not None:
        logger.info("Playlist %s updated — reloading active player (%d items)", playlist_id, len(items))
        runtime.agent._start_playlist(playlist_id, items, playlist_name=playlist_name, refresh_seconds=refresh_seconds)
    else:
        logger.info("Playlist %s updated (not currently playing, no action)", playlist_id)
    return True


def _cmd_playlist_goto(cmd: dict, command_id: str | None) -> bool:
    idx = cmd.get("index", 0)
    if runtime.agent and runtime.agent._player is not None:
        runtime.agent._player.goto(idx)
    else:
        logger.warning("playlist_goto: no active playlist player")
    return True


def _cmd_start_tab_cycle(cmd: dict, command_id: str | None) -> bool:
    interval = int(cmd.get("interval_seconds", 15))
    tab_order = cmd.get("tab_order", []) or []
    if runtime.agent:
        runtime.agent._start_tab_cycle(interval, tab_order=tab_order)
    else:
        logger.warning("start_tab_cycle: agent not ready")
    return True


def _cmd_stop_tab_cycle(cmd: dict, command_id: str | None) -> bool:
    if runtime.agent:
        runtime.agent._stop_tab_cycle()
    return True


def _cmd_open_tab(cmd: dict, command_id: str | None) -> bool:
    url = cmd.get("url", "")
    if url:
        tab = _open_tab(url)
        if tab:
            logger.info("Opened new tab: %s", url)
            # If this URL was already open, drop the just-created duplicate.
            if runtime.agent:
                runtime.agent._close_duplicate_tabs()
        else:
            logger.warning("open_tab: failed to create tab for %s", url)
            _report_command(f"open_tab: {url}", False, "Tab creation failed", command_id=command_id)
            return False
    else:
        logger.warning("open_tab: no URL provided")
        _report_command("open_tab", False, "No URL provided", command_id=command_id)
        return False
    return True


def _cmd_close_tab(cmd: dict, command_id: str | None) -> bool:
    tab_id = cmd.get("tab_id", "")
    if not tab_id:
        logger.warning("close_tab: no tab_id provided")
        _report_command("close_tab", False, "No tab_id provided", command_id=command_id)
        return False
    # Closing the last remaining tab quits Chromium (the window closes).
    # Instead, navigate it to the node's default page so the kiosk keeps
    # showing something. A playlist takeover is also stopped.
    page_tabs = list(_get_tabs())
    if len(page_tabs) <= 1:
        if runtime.agent:
            runtime.agent._stop_playlist()
            runtime.agent._stop_tab_cycle()
            default_url = runtime.agent.default_url
        else:
            default_url = "about:blank"
        logger.info("close_tab: last tab — navigating to default %s instead of closing", default_url)
        navigate(default_url)
    else:
        requests.get(f"{CDP_BASE}/json/close/{tab_id}", timeout=5)
        logger.info("Closed tab: %s", tab_id)
    return True


def _cmd_activate_tab(cmd: dict, command_id: str | None) -> bool:
    tab_id = cmd.get("tab_id", "")
    if tab_id:
        # Focusing a tab is a manual takeover — stop any running playlist or
        # tab cycle so it doesn't rotate away from the tab the operator just
        # selected.
        if runtime.agent:
            runtime.agent._stop_playlist()
            runtime.agent._stop_tab_cycle()
        requests.get(f"{CDP_BASE}/json/activate/{tab_id}", timeout=5)
        logger.info("Activated tab: %s", tab_id)
    else:
        logger.warning("activate_tab: no tab_id provided")
        _report_command("activate_tab", False, "No tab_id provided", command_id=command_id)
        return False
    return True


def _cmd_refresh_tab(cmd: dict, command_id: str | None) -> bool:
    tab_id = cmd.get("tab_id", "")
    if not tab_id:
        logger.warning("refresh_tab: no tab_id provided")
        _report_command("refresh_tab", False, "No tab_id provided", command_id=command_id)
        return False
    try:
        tabs = {t["id"]: t for t in requests.get(f"{CDP_BASE}/json", timeout=3).json() if t.get("type") == "page"}
    except Exception:
        tabs = {}
    tab = tabs.get(tab_id)
    if tab and _reload_tab(tab):
        logger.info("Refreshed tab: %s", tab_id)
    else:
        logger.warning("refresh_tab: tab %s not found or reload failed", tab_id)
        _report_command("refresh_tab", False, "Tab not found or reload failed", command_id=command_id)
        return False
    return True


def _cmd_navigate_tab(cmd: dict, command_id: str | None) -> bool:
    tab_id = cmd.get("tab_id", "")
    url = cmd.get("url", "")
    if url and not is_safe_url(url):
        logger.warning("navigate_tab: rejected disallowed URL scheme: %r", url)
        _report_command("navigate_tab", False, f"Disallowed URL scheme: {url}", command_id=command_id)
        return False
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
                return False
        except Exception as exc:
            logger.error("navigate_tab failed: %s", exc)
            _report_command("navigate_tab", False, str(exc), command_id=command_id)
            return False
    else:
        logger.warning("navigate_tab: missing tab_id or url")
        _report_command("navigate_tab", False, "Missing tab_id or url", command_id=command_id)
        return False
    return True


def _cmd_sync_browser_flags(cmd: dict, command_id: str | None) -> bool:
    if runtime.agent:
        runtime.agent._sync_browser_flags()
    else:
        logger.warning("sync_browser_flags: agent not ready")
    return True


def _cmd_sync_certs(cmd: dict, command_id: str | None) -> bool:
    if runtime.agent:
        # Reports its own success/error event (incl. malformed-cert detection),
        # so we send no generic ack.
        runtime.agent._sync_certs(command_id=command_id)
    else:
        logger.warning("sync_certs: agent not ready")
        _report_command("sync_certs", False, "agent not ready", command_id=command_id)
    return False


def _cmd_sync_hosts(cmd: dict, command_id: str | None) -> bool:
    if runtime.agent:
        runtime.agent._sync_hosts()
    else:
        logger.warning("sync_hosts: agent not ready")
    return True


def _cmd_sync_settings(cmd: dict, command_id: str | None) -> bool:
    if runtime.agent:
        # Pulls, persists, applies live, and logs its own event — so no generic ack.
        runtime.agent._sync_settings(command_id=command_id)
    else:
        logger.warning("sync_settings: agent not ready")
    return False


def _cmd_detect_capabilities(cmd: dict, command_id: str | None) -> bool:
    if runtime.agent:
        runtime.agent._run_capability_detection()
    else:
        logger.warning("detect_capabilities: agent not ready")
    return True


def _cmd_report_comms_state(cmd: dict, command_id: str | None) -> bool:
    _report_comms_state()
    return True


def _cmd_reload(cmd: dict, command_id: str | None) -> bool:
    reload_page()
    return True


def _cmd_reboot(cmd: dict, command_id: str | None) -> bool:
    # Snapshot the tabs open *right now* so they're restored on boot. The
    # periodic heartbeat that normally saves them can be up to an interval
    # stale, and the operator expects the current tab set to come back.
    if runtime.agent:
        try:
            runtime.agent._close_duplicate_tabs()
            runtime.agent._post_heartbeat()
        except Exception as exc:
            logger.warning("reboot: final tab snapshot failed: %s", exc)
    _report_command("reboot", True, command_id=command_id)
    subprocess.run(["sudo", "reboot"], check=False)
    return False


def _cmd_update_agent(cmd: dict, command_id: str | None) -> bool:
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
            json.dump(
                {
                    "ref": ref,
                    "from_version": AGENT_VERSION,
                    "issued_at": datetime.now(timezone.utc).isoformat(),
                },
                f,
            )
    except Exception as exc:
        logger.warning("update_agent: could not write update-state marker: %s", exc)
    # Launch detached — self-update re-execs into its own systemd unit so the
    # kio-agent restart at the end of the update can't kill it mid-flight.
    subprocess.Popen(
        ["sudo", "/opt/kio-agent/self-update"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _report_command("update_agent_attempt", True, f"Update started (ref {ref})", command_id=command_id)
    return False


def _cmd_display_off(cmd: dict, command_id: str | None) -> bool:
    _set_display_power(False)
    return True


def _cmd_display_on(cmd: dict, command_id: str | None) -> bool:
    _set_display_power(True)
    return True


def _cmd_standby(cmd: dict, command_id: str | None) -> bool:
    _cec_power(False)
    logger.info("CEC standby sent")
    return True


def _cmd_wake(cmd: dict, command_id: str | None) -> bool:
    _cec_power(True)
    logger.info("CEC wake sent")
    return True


def _cmd_set_resolution(cmd: dict, command_id: str | None) -> bool:
    output = cmd.get("output", "")
    mode = cmd.get("mode", "")
    rate = cmd.get("rate")
    if not output or not mode:
        _report_command("set_resolution", False, "Missing output or mode", command_id=command_id)
        return False
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
        return False
    logger.info("Resolution set: %s %s @ %s", connector, mode, rate)
    _report_command(
        "set_resolution",
        True,
        f"{output} {mode}" + (f" @ {rate} Hz" if rate is not None else ""),
        command_id=command_id,
    )
    return True


def _cmd_set_input(cmd: dict, command_id: str | None) -> bool:
    input_name = cmd.get("input", "")
    hex_val = INPUT_MAP.get(input_name)
    if hex_val:
        subprocess.run(["ddcutil", "setvcp", "60", hex_val], check=False)
        logger.info("Input switched to %s (%s)", input_name, hex_val)
        if runtime.agent:
            runtime.agent._current_input = input_name  # prevent monitor from re-reporting this change
            try:
                resp = requests.post(
                    f"{runtime.agent.api_url}/agent/heartbeat",
                    json={
                        "online": True,
                        "current_url": get_current_url(),
                        "current_input": input_name,
                        "display_on": runtime.agent._get_display_on(),
                    },
                    headers={"Authorization": f"Bearer {runtime.agent.api_token}"},
                    timeout=10,
                    verify=runtime.TLS_VERIFY,
                )
                logger.info("Input heartbeat OK (HTTP %s)", resp.status_code)
            except Exception as exc:
                logger.warning("Input heartbeat failed: %s", exc)
    else:
        logger.warning("Unknown input: %s", input_name)
        _report_command(f"set_input: {input_name}", False, "Unknown input", command_id=command_id)
        return False
    return True


def _cmd_set_brightness(cmd: dict, command_id: str | None) -> bool:
    # Gate check (defense in depth — the dashboard already hides the control
    # when the feature is disabled for this node).
    if not (runtime.agent and runtime.agent._brightness_enabled):
        _report_command("set_brightness", False, "Brightness feature disabled for this node", command_id=command_id)
        return False
    value = cmd.get("value")
    if value is None:
        _report_command("set_brightness", False, "Missing value", command_id=command_id)
        return False
    if not _set_brightness(value):
        _report_command("set_brightness", False, "ddcutil setvcp 10 failed", command_id=command_id)
        return False
    runtime.agent._current_brightness = max(0, min(100, int(value)))
    return True


# Command name -> handler. Keep in sync with the dashboard's command vocabulary.
_DISPATCH = {
    "play_playlist": _cmd_play_playlist,
    "stop_playlist": _cmd_stop_playlist,
    "sync_playlist": _cmd_sync_playlist,
    "playlist_goto": _cmd_playlist_goto,
    "start_tab_cycle": _cmd_start_tab_cycle,
    "stop_tab_cycle": _cmd_stop_tab_cycle,
    "open_tab": _cmd_open_tab,
    "close_tab": _cmd_close_tab,
    "activate_tab": _cmd_activate_tab,
    "refresh_tab": _cmd_refresh_tab,
    "navigate_tab": _cmd_navigate_tab,
    "sync_browser_flags": _cmd_sync_browser_flags,
    "sync_certs": _cmd_sync_certs,
    "sync_hosts": _cmd_sync_hosts,
    "sync_settings": _cmd_sync_settings,
    "detect_capabilities": _cmd_detect_capabilities,
    "report_comms_state": _cmd_report_comms_state,
    "reload": _cmd_reload,
    "reboot": _cmd_reboot,
    "update_agent": _cmd_update_agent,
    "display_off": _cmd_display_off,
    "display_on": _cmd_display_on,
    "standby": _cmd_standby,
    "wake": _cmd_wake,
    "set_resolution": _cmd_set_resolution,
    "set_input": _cmd_set_input,
    "set_brightness": _cmd_set_brightness,
}


def handle_command(payload: bytes) -> None:
    try:
        cmd = json.loads(payload)
    except json.JSONDecodeError:
        logger.error("Malformed command payload: %r", payload)
        return

    command = cmd.get("command")
    command_id = cmd.get("command_id")  # echoed back so the API matches by id
    logger.info("Received command: %s", command)

    handler = _DISPATCH.get(command)
    if handler is None:
        logger.warning("Unknown command: %s", command)
        _report_command(command or "unknown", False, "Unknown command", command_id=command_id)
        return

    try:
        if handler(cmd, command_id):
            # The dashboard already recorded a human-readable label; the agent only
            # needs to ack by id (or by bare command name for agent-initiated commands).
            _report_command(command or "unknown", True, command_id=command_id)
    except Exception as exc:
        logger.error("Command %s failed: %s", command, exc)
        _report_command(command or "unknown", False, str(exc), command_id=command_id)
