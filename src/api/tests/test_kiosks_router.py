"""Router tests for /kiosks — service layer is mocked, HTTP behaviour is verified."""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tests.conftest import make_kiosk

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cmd_log(**kwargs):
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=uuid.uuid4(),
        command="reload",
        source="dashboard",
        sent_at=now,
        agent_success=None,
        agent_message=None,
        agent_at=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# GET /kiosks
# ---------------------------------------------------------------------------


async def test_list_kiosks_empty(client):
    with patch("app.routers.kiosks.kiosk_service.get_all", new_callable=AsyncMock) as m:
        m.return_value = []
        r = await client.get("/kiosks")

    assert r.status_code == 200
    assert r.json() == []


async def test_list_kiosks_returns_items(client):
    kiosk = make_kiosk(name="Lobby")
    with patch("app.routers.kiosks.kiosk_service.get_all", new_callable=AsyncMock) as m:
        m.return_value = [kiosk]
        r = await client.get("/kiosks")

    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["name"] == "Lobby"


# ---------------------------------------------------------------------------
# POST /kiosks
# ---------------------------------------------------------------------------


async def test_create_kiosk_returns_201(client):
    kiosk = make_kiosk(name="Hall", hostname="hall.local", status="unknown")
    with patch("app.routers.kiosks.kiosk_service.create", new_callable=AsyncMock) as m:
        m.return_value = kiosk
        r = await client.post("/kiosks", json={"name": "Hall", "hostname": "hall.local"})

    assert r.status_code == 201
    assert r.json()["name"] == "Hall"
    assert r.json()["status"] == "unknown"


async def test_create_kiosk_missing_field_returns_422(client):
    r = await client.post("/kiosks", json={"name": "Missing hostname"})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# GET /kiosks/{id}
# ---------------------------------------------------------------------------


async def test_get_kiosk_found(client):
    kiosk = make_kiosk()
    with patch("app.routers.kiosks.kiosk_service.get_by_id", new_callable=AsyncMock) as m:
        m.return_value = kiosk
        r = await client.get(f"/kiosks/{kiosk.id}")

    assert r.status_code == 200
    assert r.json()["id"] == str(kiosk.id)


async def test_get_kiosk_not_found(client):
    with patch("app.routers.kiosks.kiosk_service.get_by_id", new_callable=AsyncMock) as m:
        m.return_value = None
        r = await client.get(f"/kiosks/{uuid.uuid4()}")

    assert r.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /kiosks/{id}
# ---------------------------------------------------------------------------


async def test_update_kiosk(client):
    kiosk = make_kiosk(name="Renamed")
    with patch("app.routers.kiosks.kiosk_service.update_kiosk", new_callable=AsyncMock) as m:
        m.return_value = kiosk
        r = await client.patch(f"/kiosks/{kiosk.id}", json={"name": "Renamed"})

    assert r.status_code == 200
    assert r.json()["name"] == "Renamed"


async def test_update_kiosk_not_found(client):
    with patch("app.routers.kiosks.kiosk_service.update_kiosk", new_callable=AsyncMock) as m:
        m.return_value = None
        r = await client.patch(f"/kiosks/{uuid.uuid4()}", json={"name": "X"})

    assert r.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /kiosks/{id}
# ---------------------------------------------------------------------------


async def test_delete_kiosk(client):
    with patch("app.routers.kiosks.kiosk_service.delete", new_callable=AsyncMock) as m:
        m.return_value = True
        r = await client.delete(f"/kiosks/{uuid.uuid4()}")

    assert r.status_code == 204


async def test_delete_kiosk_not_found(client):
    with patch("app.routers.kiosks.kiosk_service.delete", new_callable=AsyncMock) as m:
        m.return_value = False
        r = await client.delete(f"/kiosks/{uuid.uuid4()}")

    assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /kiosks/{id}/command
# ---------------------------------------------------------------------------


async def test_send_valid_command(client):
    kiosk = make_kiosk()
    with (
        patch("app.routers.kiosks.kiosk_service.get_by_id", new_callable=AsyncMock, return_value=kiosk),
        patch("app.routers.kiosks.publish_command") as mock_pub,
    ):
        r = await client.post(f"/kiosks/{kiosk.id}/command", json={"command": "reload"})

    assert r.status_code == 204
    mock_pub.assert_called_once_with(str(kiosk.id), {"command": "reload"})


async def test_send_invalid_command_returns_400(client):
    r = await client.post(f"/kiosks/{uuid.uuid4()}/command", json={"command": "explode"})
    assert r.status_code == 400


async def test_send_command_kiosk_not_found(client):
    with (patch("app.routers.kiosks.kiosk_service.get_by_id", new_callable=AsyncMock, return_value=None),):
        r = await client.post(f"/kiosks/{uuid.uuid4()}/command", json={"command": "reload"})

    assert r.status_code == 404


async def test_all_allowed_commands_accepted(client):
    kiosk = make_kiosk()
    commands = [
        "reload",
        "reboot",
        "display_off",
        "display_on",
        "standby",
        "wake",
        "detect_capabilities",
        "sync_browser_flags",
        "sync_hosts",
    ]
    for cmd in commands:
        with (
            patch("app.routers.kiosks.kiosk_service.get_by_id", new_callable=AsyncMock, return_value=kiosk),
            patch("app.routers.kiosks.publish_command"),
        ):
            r = await client.post(f"/kiosks/{kiosk.id}/command", json={"command": cmd})
        assert r.status_code == 204, f"command {cmd!r} should be allowed"


# ---------------------------------------------------------------------------
# POST /kiosks/{id}/navigate
# ---------------------------------------------------------------------------


async def test_navigate(client):
    kiosk = make_kiosk()
    with (
        patch("app.routers.kiosks.kiosk_service.get_by_id", new_callable=AsyncMock, return_value=kiosk),
        patch("app.routers.kiosks.publish_nav") as mock_nav,
    ):
        r = await client.post(f"/kiosks/{kiosk.id}/navigate", json={"url": "https://example.com"})

    assert r.status_code == 204
    mock_nav.assert_called_once_with(str(kiosk.id), "https://example.com")


async def test_navigate_kiosk_not_found(client):
    with patch("app.routers.kiosks.kiosk_service.get_by_id", new_callable=AsyncMock, return_value=None):
        r = await client.post(f"/kiosks/{uuid.uuid4()}/navigate", json={"url": "https://example.com"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /kiosks/{id}/input
# ---------------------------------------------------------------------------


async def test_set_valid_input(client):
    kiosk = make_kiosk()
    for inp in ["dp1", "dp2", "hdmi1", "hdmi2"]:
        with (
            patch("app.routers.kiosks.kiosk_service.get_by_id", new_callable=AsyncMock, return_value=kiosk),
            patch("app.routers.kiosks.publish_command"),
        ):
            r = await client.post(f"/kiosks/{kiosk.id}/input", json={"input": inp})
        assert r.status_code == 204, f"input {inp!r} should be allowed"


async def test_set_invalid_input_returns_400(client):
    r = await client.post(f"/kiosks/{uuid.uuid4()}/input", json={"input": "usb"})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# PUT /kiosks/{id}/brightness
# ---------------------------------------------------------------------------


async def test_set_brightness_valid_dispatches_command(client):
    kiosk = make_kiosk()
    with (
        patch("app.routers.kiosks.kiosk_service.get_by_id", new_callable=AsyncMock, return_value=kiosk),
        patch("app.routers.kiosks.publish_command") as mock_pub,
    ):
        r = await client.put(f"/kiosks/{kiosk.id}/brightness", json={"value": 40})
    assert r.status_code == 204
    # The set_brightness command (with the value) is published to the node.
    payload = mock_pub.call_args.args[1]
    assert payload["command"] == "set_brightness"
    assert payload["value"] == 40


async def test_set_brightness_out_of_bounds_returns_422(client):
    for bad in (-1, 101):
        r = await client.put(f"/kiosks/{uuid.uuid4()}/brightness", json={"value": bad})
        assert r.status_code == 422, f"value {bad} should be rejected"


async def test_set_brightness_kiosk_not_found(client):
    with patch("app.routers.kiosks.kiosk_service.get_by_id", new_callable=AsyncMock, return_value=None):
        r = await client.put(f"/kiosks/{uuid.uuid4()}/brightness", json={"value": 50})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /kiosks/{id}/command-log
# ---------------------------------------------------------------------------


async def test_command_log_empty(client):
    kiosk = make_kiosk()
    with patch("app.routers.kiosks.kiosk_service.get_by_id", new_callable=AsyncMock, return_value=kiosk):
        r = await client.get(f"/kiosks/{kiosk.id}/command-log")
    assert r.status_code == 200


async def test_command_log_returns_200(client):
    kiosk = make_kiosk()
    with patch("app.routers.kiosks.kiosk_service.get_by_id", new_callable=AsyncMock, return_value=kiosk):
        r = await client.get(f"/kiosks/{kiosk.id}/command-log")
    assert r.status_code == 200


async def test_command_log_kiosk_not_found(client):
    with patch("app.routers.kiosks.kiosk_service.get_by_id", new_callable=AsyncMock, return_value=None):
        r = await client.get(f"/kiosks/{uuid.uuid4()}/command-log")
    assert r.status_code == 404


async def test_command_log_x_total_count_header(client):
    kiosk = make_kiosk()
    with patch("app.routers.kiosks.kiosk_service.get_by_id", new_callable=AsyncMock, return_value=kiosk):
        r = await client.get(f"/kiosks/{kiosk.id}/command-log")
    assert "x-total-count" in r.headers


# ---------------------------------------------------------------------------
# PUT /kiosks/{id}/meta/{key}
# ---------------------------------------------------------------------------


async def test_set_meta(client):
    kiosk = make_kiosk()

    with (
        patch("app.routers.kiosks.kiosk_service.get_by_id", new_callable=AsyncMock, return_value=kiosk),
        patch("app.routers.kiosks.publish_command"),
    ):
        r = await client.put(
            f"/kiosks/{kiosk.id}/meta/location",
            json={"key": "location", "value": "lobby"},
        )

    assert r.status_code == 200


async def test_set_meta_kiosk_not_found(client):
    with patch("app.routers.kiosks.kiosk_service.get_by_id", new_callable=AsyncMock, return_value=None):
        r = await client.put(
            f"/kiosks/{uuid.uuid4()}/meta/key",
            json={"key": "key", "value": "val"},
        )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /kiosks/{id}/meta/{key}
# ---------------------------------------------------------------------------


async def test_delete_meta_kiosk_not_found(client):
    with patch("app.routers.kiosks.kiosk_service.get_by_id", new_callable=AsyncMock, return_value=None):
        r = await client.delete(f"/kiosks/{uuid.uuid4()}/meta/somekey")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /kiosks/{id}/meta
# ---------------------------------------------------------------------------


async def test_list_meta_empty(client):
    kiosk = make_kiosk(meta_rows=[])
    with patch("app.routers.kiosks.kiosk_service.get_by_id", new_callable=AsyncMock, return_value=kiosk):
        r = await client.get(f"/kiosks/{kiosk.id}/meta")
    assert r.status_code == 200
    assert r.json() == []


async def test_list_meta_kiosk_not_found(client):
    with patch("app.routers.kiosks.kiosk_service.get_by_id", new_callable=AsyncMock, return_value=None):
        r = await client.get(f"/kiosks/{uuid.uuid4()}/meta")
    assert r.status_code == 404
