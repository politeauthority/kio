"""Tests for MQTT command dispatch with mocked I/O.

Verifies the dispatch table's coverage and that the refactored handlers preserve
the original ack semantics: fall-through commands send a generic success ack,
while self-reporting / early-return commands (reboot, update, failures) do not.
"""

import json
from unittest.mock import MagicMock

import pytest

from kio_agent import commands, runtime

EXPECTED_COMMANDS = {
    "play_playlist",
    "stop_playlist",
    "sync_playlist",
    "playlist_goto",
    "start_tab_cycle",
    "stop_tab_cycle",
    "open_tab",
    "close_tab",
    "activate_tab",
    "refresh_tab",
    "navigate_tab",
    "sync_browser_flags",
    "sync_certs",
    "sync_hosts",
    "sync_settings",
    "detect_capabilities",
    "report_comms_state",
    "reload",
    "reboot",
    "update_agent",
    "display_off",
    "display_on",
    "standby",
    "wake",
    "set_resolution",
    "set_input",
    "set_brightness",
}


@pytest.fixture(autouse=True)
def isolate_io(monkeypatch):
    """Replace all outward I/O in the commands module with mocks so no test can
    shell out (e.g. reboot) or hit the network."""
    monkeypatch.setattr(commands, "subprocess", MagicMock())
    monkeypatch.setattr(commands, "requests", MagicMock())


@pytest.fixture
def reports(monkeypatch):
    """Capture every _report_command call made from the commands module."""
    calls = []

    def rec(command, success, message=None, command_id=None):
        calls.append({"command": command, "success": success, "message": message, "command_id": command_id})

    monkeypatch.setattr(commands, "_report_command", rec)
    return calls


@pytest.fixture
def agent(monkeypatch):
    a = MagicMock()
    a.default_url = "http://default"
    a._brightness_enabled = True
    a._player = None
    monkeypatch.setattr(runtime, "agent", a)
    return a


@pytest.fixture
def no_agent(monkeypatch):
    monkeypatch.setattr(runtime, "agent", None)


def _payload(command, **extra):
    return json.dumps({"command": command, "command_id": "cid-1", **extra}).encode()


# --- Dispatch table ---------------------------------------------------------


def test_dispatch_covers_exactly_expected_commands():
    assert set(commands._DISPATCH) == EXPECTED_COMMANDS


def test_dispatch_values_are_callable():
    assert all(callable(h) for h in commands._DISPATCH.values())


# --- Parsing / unknown ------------------------------------------------------


def test_malformed_json_is_ignored(reports):
    commands.handle_command(b"{ not json")
    assert reports == []


def test_unknown_command_reports_failure(reports):
    commands.handle_command(_payload("frobnicate"))
    assert len(reports) == 1
    assert reports[0]["command"] == "frobnicate"
    assert reports[0]["success"] is False
    assert reports[0]["message"] == "Unknown command"
    assert reports[0]["command_id"] == "cid-1"


# --- Fall-through commands send the generic success ack ---------------------


def test_reload_sends_generic_ack(reports, monkeypatch):
    reload_page = MagicMock()
    monkeypatch.setattr(commands, "reload_page", reload_page)
    commands.handle_command(_payload("reload"))
    reload_page.assert_called_once()
    assert reports == [{"command": "reload", "success": True, "message": None, "command_id": "cid-1"}]


def test_display_off_sends_generic_ack(reports, monkeypatch):
    set_power = MagicMock()
    monkeypatch.setattr(commands, "_set_display_power", set_power)
    commands.handle_command(_payload("display_off"))
    set_power.assert_called_once_with(False)
    assert reports == [{"command": "display_off", "success": True, "message": None, "command_id": "cid-1"}]


# --- Self-reporting / early-return commands send NO generic ack -------------


def test_reboot_reports_itself_and_no_generic_ack(reports, agent):
    commands.handle_command(_payload("reboot"))
    # Exactly one report — reboot's own — not a second generic ack.
    assert len(reports) == 1
    assert reports[0]["command"] == "reboot"
    assert reports[0]["success"] is True
    commands.subprocess.run.assert_called_once()  # the sudo reboot


def test_sync_certs_delegates_to_agent_without_generic_ack(reports, agent):
    commands.handle_command(_payload("sync_certs"))
    agent._sync_certs.assert_called_once_with(command_id="cid-1")
    assert reports == []  # the agent method owns its own reporting


def test_sync_certs_without_agent_reports_failure(reports, no_agent):
    commands.handle_command(_payload("sync_certs"))
    assert len(reports) == 1
    assert reports[0]["command"] == "sync_certs"
    assert reports[0]["success"] is False


# --- Failure paths ----------------------------------------------------------


def test_open_tab_without_url_reports_failure_only(reports, agent):
    commands.handle_command(_payload("open_tab"))
    assert len(reports) == 1
    assert reports[0]["command"] == "open_tab"
    assert reports[0]["success"] is False
    assert reports[0]["message"] == "No URL provided"


def test_set_input_unknown_reports_failure_only(reports, agent):
    commands.handle_command(_payload("set_input", input="vga1"))
    assert len(reports) == 1
    assert reports[0]["command"] == "set_input: vga1"
    assert reports[0]["success"] is False
    assert reports[0]["message"] == "Unknown input"


def test_set_brightness_disabled_reports_failure(reports, monkeypatch):
    a = MagicMock()
    a._brightness_enabled = False
    monkeypatch.setattr(runtime, "agent", a)
    commands.handle_command(_payload("set_brightness", value=50))
    assert len(reports) == 1
    assert reports[0]["success"] is False
    assert "disabled" in reports[0]["message"]


def test_handler_exception_is_reported(reports, monkeypatch):
    boom = MagicMock(side_effect=RuntimeError("kaboom"))
    monkeypatch.setattr(commands, "reload_page", boom)
    commands.handle_command(_payload("reload"))
    assert len(reports) == 1
    assert reports[0]["command"] == "reload"
    assert reports[0]["success"] is False
    assert "kaboom" in reports[0]["message"]


# --- set_resolution double-report behavior is preserved ---------------------


def test_set_resolution_success_reports_detail_then_generic_ack(reports, monkeypatch):
    monkeypatch.setattr(commands, "_write_kanshi_config", MagicMock(return_value=False))
    monkeypatch.setattr(commands, "_current_connector", MagicMock(return_value="HDMI-A-1"))
    commands.subprocess.run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    commands.handle_command(_payload("set_resolution", output="HDMI-A-1", mode="1920x1080", rate=60))
    # Original behavior: a detailed report followed by the generic trailing ack.
    assert len(reports) == 2
    assert reports[0]["command"] == "set_resolution"
    assert reports[0]["success"] is True
    assert reports[1]["command"] == "set_resolution"
    assert reports[1]["success"] is True
    assert reports[1]["message"] is None  # the generic ack carries no message


def test_set_resolution_missing_args_reports_failure_only(reports):
    commands.handle_command(_payload("set_resolution", output="", mode=""))
    assert len(reports) == 1
    assert reports[0]["success"] is False
    assert reports[0]["message"] == "Missing output or mode"
