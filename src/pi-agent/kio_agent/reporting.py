"""Best-effort HTTP reporting back to the kio API.

Command acks, hardware info, hardware-detect logs, and file-permission errors.
Every function no-ops when the agent instance isn't wired up yet and swallows
network errors — a reporting failure must never crash its caller.
"""

import requests

from kio_agent import runtime
from kio_agent.constants import logger


def _report_hardware_info(hw_info: dict) -> None:
    if not runtime.agent:
        return
    try:
        requests.put(
            f"{runtime.agent.api_url}/agent/meta/hardware_info",
            json={"value": hw_info},
            headers={"Authorization": f"Bearer {runtime.agent.api_token}"},
            timeout=10,
            verify=runtime.TLS_VERIFY,
        )
    except Exception as exc:
        logger.warning("Failed to report hardware info: %s", exc)


def _report_detect_log(caps: list[str], probes: dict, hw_info: dict) -> None:
    if not runtime.agent:
        return
    try:
        requests.post(
            f"{runtime.agent.api_url}/agent/hardware-detect-log",
            json={"capabilities": caps, "probes": probes, "hardware_info": hw_info},
            headers={"Authorization": f"Bearer {runtime.agent.api_token}"},
            timeout=10,
            verify=runtime.TLS_VERIFY,
        )
    except Exception as exc:
        logger.warning("Failed to report detect log: %s", exc)


def _report_file_error(path: str, process: str = "agent") -> None:
    if not runtime.agent:
        return
    try:
        requests.post(
            f"{runtime.agent.api_url}/agent/file-permission-error",
            json={"file": path, "process": process},
            headers={"Authorization": f"Bearer {runtime.agent.api_token}"},
            timeout=5,
            verify=runtime.TLS_VERIFY,
        )
    except Exception as exc:
        logger.debug("Failed to report file permission error: %s", exc)


def _report_command(
    command: str,
    success: bool,
    message: str | None = None,
    command_id: str | None = None,
) -> None:
    if not runtime.agent:
        return
    try:
        body: dict = {"command": command, "success": success, "message": message}
        if command_id:
            body["command_id"] = command_id  # API matches the dashboard record by id
        resp = requests.post(
            f"{runtime.agent.api_url}/agent/command-log",
            json=body,
            headers={"Authorization": f"Bearer {runtime.agent.api_token}"},
            timeout=5,
            verify=runtime.TLS_VERIFY,
        )
        if resp.status_code not in (200, 204):
            logger.warning("command-log ack returned HTTP %s for %s (id=%s)", resp.status_code, command, command_id)
        else:
            logger.info("command-log ack OK: %s success=%s (id=%s)", command, success, command_id)
    except Exception as exc:
        logger.warning("Failed to report command result for %s: %s", command, exc)
