"""Router tests for /event-logs — verifies the HTTP layer with a mocked session."""

import uuid

# ---------------------------------------------------------------------------
# GET /event-logs
# ---------------------------------------------------------------------------


async def test_search_returns_200_and_total_header(client):
    r = await client.get("/event-logs")
    assert r.status_code == 200
    assert r.json() == []
    assert r.headers["X-Total-Count"] == "0"


async def test_search_accepts_all_filters(client):
    r = await client.get(
        "/event-logs",
        params={
            "kiosk_id": str(uuid.uuid4()),
            "command": "reload",
            "status": "ok",
            "search": "boot",
            "limit": 50,
            "offset": 10,
        },
    )
    assert r.status_code == 200


async def test_search_rejects_limit_over_max(client):
    r = await client.get("/event-logs", params={"limit": 500})
    assert r.status_code == 422


async def test_search_rejects_negative_offset(client):
    r = await client.get("/event-logs", params={"offset": -1})
    assert r.status_code == 422


async def test_search_rejects_malformed_kiosk_id(client):
    r = await client.get("/event-logs", params={"kiosk_id": "not-a-uuid"})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# GET /event-logs/commands
# ---------------------------------------------------------------------------


async def test_list_commands_returns_200(client):
    r = await client.get("/event-logs/commands")
    assert r.status_code == 200
    assert r.json() == []
