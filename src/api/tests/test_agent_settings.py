"""Tests for agent settings: pure service helpers + the dashboard/agent routers."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import settings_service as ss

# ---------------------------------------------------------------------------
# settings_service pure helpers
# ---------------------------------------------------------------------------


def test_coerce_setting_valid():
    assert ss.coerce_setting("heartbeat_interval_seconds", "60") == 60


def test_coerce_setting_unknown_key():
    with pytest.raises(ValueError):
        ss.coerce_setting("nope", 5)


def test_coerce_setting_out_of_bounds():
    with pytest.raises(ValueError):
        ss.coerce_setting("heartbeat_interval_seconds", 1)  # below min of 5


def test_coerce_setting_not_an_int():
    with pytest.raises(ValueError):
        ss.coerce_setting("heartbeat_interval_seconds", "abc")


def test_effective_settings_applies_overridable():
    merged = ss.effective_settings({**ss.AGENT_SETTING_DEFAULTS}, {"heartbeat_interval_seconds": 90})
    assert merged["heartbeat_interval_seconds"] == 90


def test_effective_settings_ignores_non_overridable():
    merged = ss.effective_settings({**ss.AGENT_SETTING_DEFAULTS}, {"event_log_purge_days": 1})
    assert merged["event_log_purge_days"] == ss.AGENT_SETTING_DEFAULTS["event_log_purge_days"]


def test_effective_settings_ignores_malformed_override():
    merged = ss.effective_settings({**ss.AGENT_SETTING_DEFAULTS}, {"heartbeat_interval_seconds": "bad"})
    assert merged["heartbeat_interval_seconds"] == ss.AGENT_SETTING_DEFAULTS["heartbeat_interval_seconds"]


def test_effective_settings_handles_none():
    merged = ss.effective_settings({**ss.AGENT_SETTING_DEFAULTS}, None)
    assert merged == ss.AGENT_SETTING_DEFAULTS


# ---------------------------------------------------------------------------
# Brightness gate: per-node overridable + node-affecting (refreshes live)
# ---------------------------------------------------------------------------


def test_brightness_gate_defaults_off():
    assert ss.AGENT_SETTING_DEFAULTS["brightness_enabled"] == 0


def test_brightness_keys_are_overridable_and_node_affecting():
    for key in ("brightness_enabled", "brightness_default"):
        assert key in ss.OVERRIDABLE_KEYS
        assert key in ss.NODE_AFFECTING_KEYS


def test_effective_settings_applies_per_node_brightness_gate():
    merged = ss.effective_settings({**ss.AGENT_SETTING_DEFAULTS}, {"brightness_enabled": 1})
    assert merged["brightness_enabled"] == 1  # one node enabled while the fleet default stays off


def test_coerce_brightness_enabled_bounds():
    assert ss.coerce_setting("brightness_enabled", "1") == 1
    with pytest.raises(ValueError):
        ss.coerce_setting("brightness_enabled", 2)  # gate is 0/1 only


async def test_put_notifies_nodes_on_brightness_gate_change(client):
    before = dict(ss.AGENT_SETTING_DEFAULTS)
    after = {**before, "brightness_enabled": 1}
    with (
        patch("app.routers.agent_settings.settings_service.get_global_settings", new=AsyncMock(return_value=before)),
        patch("app.routers.agent_settings.settings_service.update_global_settings", new=AsyncMock(return_value=after)),
        patch("app.routers.agent_settings._notify_all_nodes", new=AsyncMock()) as notify,
    ):
        r = await client.put("/settings/agent", json={"brightness_enabled": 1})
    assert r.status_code == 200
    notify.assert_awaited_once()  # flipping the gate bounces the fleet so nodes refresh live


# ---------------------------------------------------------------------------
# GET /settings/agent (dashboard) — empty DB returns defaults
# ---------------------------------------------------------------------------


async def test_get_agent_settings_returns_defaults(client):
    r = await client.get("/settings/agent")
    assert r.status_code == 200
    assert r.json() == ss.AGENT_SETTING_DEFAULTS


async def test_put_agent_settings_valid(client):
    r = await client.put("/settings/agent", json={"heartbeat_interval_seconds": 45})
    assert r.status_code == 200
    # Body echoes the full settings set (mock DB doesn't persist, so it's defaults)
    assert "heartbeat_interval_seconds" in r.json()


async def test_put_agent_settings_out_of_bounds(client):
    r = await client.put("/settings/agent", json={"heartbeat_interval_seconds": 1})
    assert r.status_code == 422


async def test_put_agent_settings_empty_is_noop(client):
    r = await client.put("/settings/agent", json={})
    assert r.status_code == 200
    assert r.json() == ss.AGENT_SETTING_DEFAULTS


# ---------------------------------------------------------------------------
# GET /agent/settings (node) — defaults when node has no overrides
# ---------------------------------------------------------------------------


async def test_agent_settings_endpoint_defaults(agent_client):
    client, kiosk, session = agent_client
    r = await client.get("/agent/settings")
    assert r.status_code == 200
    assert r.json() == ss.AGENT_SETTING_DEFAULTS


# ---------------------------------------------------------------------------
# Node notification on settings change
# ---------------------------------------------------------------------------


async def test_put_notifies_nodes_on_node_affecting_change(client):
    before = dict(ss.AGENT_SETTING_DEFAULTS)
    after = {**before, "heartbeat_interval_seconds": 99}
    with (
        patch("app.routers.agent_settings.settings_service.get_global_settings", new=AsyncMock(return_value=before)),
        patch("app.routers.agent_settings.settings_service.update_global_settings", new=AsyncMock(return_value=after)),
        patch("app.routers.agent_settings._notify_all_nodes", new=AsyncMock()) as notify,
    ):
        r = await client.put("/settings/agent", json={"heartbeat_interval_seconds": 99})
    assert r.status_code == 200
    notify.assert_awaited_once()


async def test_put_no_notify_on_server_only_change(client):
    before = dict(ss.AGENT_SETTING_DEFAULTS)
    after = {**before, "event_log_purge_days": 30}
    with (
        patch("app.routers.agent_settings.settings_service.get_global_settings", new=AsyncMock(return_value=before)),
        patch("app.routers.agent_settings.settings_service.update_global_settings", new=AsyncMock(return_value=after)),
        patch("app.routers.agent_settings._notify_all_nodes", new=AsyncMock()) as notify,
    ):
        r = await client.put("/settings/agent", json={"event_log_purge_days": 30})
    assert r.status_code == 200
    notify.assert_not_awaited()


async def test_notify_all_nodes_publishes_sync_settings_per_kiosk():
    from app.routers import agent_settings as mod

    ids = [(uuid.uuid4(),), (uuid.uuid4(),), (uuid.uuid4(),)]
    result = MagicMock()
    result.all.return_value = ids
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    with patch("app.routers.agent_settings.publish_command") as pub:
        await mod._notify_all_nodes(session)

    assert pub.call_count == 3
    for call in pub.call_args_list:
        assert call.args[1] == {"command": "sync_settings"}
