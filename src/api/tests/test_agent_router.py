"""Router tests for /agent/* — get_node_kiosk is overridden with a fixed kiosk."""

import uuid
from unittest.mock import AsyncMock, MagicMock

from app.models.agent_update_log import AgentUpdateLog

# ---------------------------------------------------------------------------
# POST /agent/heartbeat
# ---------------------------------------------------------------------------


async def test_heartbeat_online(agent_client):
    client, kiosk, session = agent_client
    session.commit = AsyncMock()

    r = await client.post("/agent/heartbeat", json={"online": True})

    assert r.status_code == 204
    assert kiosk.status == "online"


async def test_heartbeat_offline(agent_client):
    client, kiosk, session = agent_client
    session.commit = AsyncMock()

    r = await client.post("/agent/heartbeat", json={"online": False})

    assert r.status_code == 204
    assert kiosk.status == "offline"


async def test_heartbeat_updates_url(agent_client):
    client, kiosk, session = agent_client
    session.commit = AsyncMock()

    r = await client.post(
        "/agent/heartbeat",
        json={"online": True, "current_url": "https://example.com"},
    )

    assert r.status_code == 204
    assert kiosk.current_url == "https://example.com"


async def test_heartbeat_updates_ip_and_version(agent_client):
    client, kiosk, session = agent_client
    session.commit = AsyncMock()

    r = await client.post(
        "/agent/heartbeat",
        json={
            "online": True,
            "ip_address": "192.168.1.50",
            "agent_version": "1.2.3",
            "device_type": "pi5",
        },
    )

    assert r.status_code == 204
    assert kiosk.ip_address == "192.168.1.50"
    assert kiosk.agent_version == "1.2.3"
    assert kiosk.device_type == "pi5"


async def test_update_log_creates_row(agent_client):
    client, kiosk, session = agent_client
    session.commit = AsyncMock()
    session.add = MagicMock()

    r = await client.post(
        "/agent/update-log",
        json={
            "status": "success",
            "log": "RESULT: ok (exit 0)",
            "ref": "v0.4.0",
            "from_version": "0.2.0",
            "to_version": "0.4.0",
        },
    )

    assert r.status_code == 204
    session.add.assert_called_once()
    row = session.add.call_args[0][0]
    assert isinstance(row, AgentUpdateLog)
    assert row.kiosk_id == kiosk.id
    assert row.status == "success"
    assert row.to_version == "0.4.0"


async def test_update_log_reconciles_command(agent_client):
    client, kiosk, session = agent_client
    session.commit = AsyncMock()
    session.add = MagicMock()

    # Matching dashboard command row the agent's update should reconcile.
    cmd_id = uuid.uuid4()
    record = MagicMock(agent_success=None, agent_message=None, agent_at=None)
    result = MagicMock()
    result.scalar_one_or_none.return_value = record
    session.execute = AsyncMock(return_value=result)

    r = await client.post(
        "/agent/update-log",
        json={"status": "success", "to_version": "0.4.0", "command_id": str(cmd_id)},
    )

    assert r.status_code == 204
    assert record.agent_success is True
    assert record.agent_at is not None


async def test_heartbeat_new_boot_logs_event(agent_client):
    client, kiosk, session = agent_client
    session.commit = AsyncMock()
    session.add = MagicMock()
    kiosk.last_boot_id = "old-boot"
    kiosk.status = "online"

    r = await client.post(
        "/agent/heartbeat",
        json={"online": True, "boot_id": "new-boot"},
    )

    assert r.status_code == 204
    session.add.assert_called_once()
    from app.models.command_log import CommandLog

    log = session.add.call_args[0][0]
    assert isinstance(log, CommandLog)
    assert "rebooted" in log.command


async def test_heartbeat_came_back_online_logs_event(agent_client):
    client, kiosk, session = agent_client
    session.commit = AsyncMock()
    session.add = MagicMock()
    kiosk.status = "offline"
    kiosk.last_boot_id = "same-boot"

    r = await client.post(
        "/agent/heartbeat",
        json={"online": True, "boot_id": "same-boot"},
    )

    assert r.status_code == 204
    session.add.assert_called_once()

    log = session.add.call_args[0][0]
    assert "online" in log.command


# ---------------------------------------------------------------------------
# GET /agent/config
# ---------------------------------------------------------------------------


async def test_get_config(agent_client):
    client, kiosk, _ = agent_client

    r = await client.get("/agent/config")

    assert r.status_code == 200
    data = r.json()
    assert data["kiosk_id"] == str(kiosk.id)
    assert "mqtt_topic_prefix" in data
    assert "mqtt_host" in data
    assert "mqtt_port" in data


# ---------------------------------------------------------------------------
# GET /agent/browser-flags
# ---------------------------------------------------------------------------


async def test_get_browser_flags(agent_client):
    client, kiosk, _ = agent_client
    kiosk.browser_flags = ["--force-dark-mode", "--hide-scrollbars"]

    r = await client.get("/agent/browser-flags")

    assert r.status_code == 200
    assert r.json() == ["--force-dark-mode", "--hide-scrollbars"]


async def test_get_browser_flags_empty(agent_client):
    client, kiosk, _ = agent_client
    kiosk.browser_flags = []

    r = await client.get("/agent/browser-flags")

    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# GET /agent/meta
# ---------------------------------------------------------------------------


async def test_get_meta(agent_client):
    client, kiosk, _ = agent_client
    kiosk.meta = {"floor": "2", "location": "lobby"}

    r = await client.get("/agent/meta")

    assert r.status_code == 200
    assert r.json() == {"floor": "2", "location": "lobby"}


# ---------------------------------------------------------------------------
# PUT /agent/meta/{key}
# ---------------------------------------------------------------------------


async def test_put_meta_new_key(agent_client):
    client, kiosk, session = agent_client
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result_mock)
    session.add = MagicMock()
    session.commit = AsyncMock()

    r = await client.put("/agent/meta/location", json={"value": "hallway"})

    assert r.status_code == 204
    session.add.assert_called_once()


async def test_put_meta_existing_key(agent_client):
    client, kiosk, session = agent_client
    from app.models.node_meta import NodeMeta

    existing = MagicMock(spec=NodeMeta)
    existing.value = "old"
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = existing
    session.execute = AsyncMock(return_value=result_mock)
    session.commit = AsyncMock()

    r = await client.put("/agent/meta/location", json={"value": "new-value"})

    assert r.status_code == 204
    assert existing.value == "new-value"


# ---------------------------------------------------------------------------
# POST /agent/command-log
# ---------------------------------------------------------------------------


async def test_log_command_creates_new_record(agent_client):
    client, kiosk, session = agent_client
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result_mock)
    session.add = MagicMock()
    session.commit = AsyncMock()

    r = await client.post(
        "/agent/command-log",
        json={"command": "reload", "success": True, "message": "done"},
    )

    assert r.status_code == 204
    session.add.assert_called_once()
    from app.models.command_log import CommandLog

    log = session.add.call_args[0][0]
    assert isinstance(log, CommandLog)
    assert log.command == "reload"
    assert log.agent_success is True
    assert log.source == "agent"


async def test_log_command_updates_pending_record(agent_client):
    client, kiosk, session = agent_client
    from app.models.command_log import CommandLog

    pending = MagicMock(spec=CommandLog)
    pending.agent_success = None
    pending.agent_message = None
    pending.agent_at = None

    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = pending
    session.execute = AsyncMock(return_value=result_mock)
    session.add = MagicMock()
    session.commit = AsyncMock()

    r = await client.post(
        "/agent/command-log",
        json={"command": "reload", "success": True, "message": "ok"},
    )

    assert r.status_code == 204
    assert pending.agent_success is True
    assert pending.agent_message == "ok"
    assert pending.agent_at is not None
    session.add.assert_not_called()  # updated in place, not added
