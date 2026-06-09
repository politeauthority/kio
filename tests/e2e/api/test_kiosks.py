import httpx
import pytest


def test_list_kiosks_returns_200(api: httpx.Client):
    r = api.get("/kiosks")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_create_kiosk_returns_201(api: httpx.Client, test_kiosk: dict):
    assert test_kiosk["id"]
    assert test_kiosk["name"].startswith("e2e-")
    assert test_kiosk["status"] == "unknown"


def test_get_kiosk(api: httpx.Client, test_kiosk: dict):
    r = api.get(f"/kiosks/{test_kiosk['id']}")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == test_kiosk["id"]
    assert data["name"] == test_kiosk["name"]


def test_update_kiosk(api: httpx.Client, test_kiosk: dict):
    new_name = test_kiosk["name"] + "-renamed"
    r = api.patch(f"/kiosks/{test_kiosk['id']}", json={"name": new_name})
    assert r.status_code == 200
    assert r.json()["name"] == new_name


def test_get_kiosk_not_found(api: httpx.Client):
    r = api.get("/kiosks/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


def test_delete_kiosk(api: httpx.Client, auth_token: str, api_url: str):
    # Create a dedicated kiosk just for the delete test
    r = api.post("/kiosks", json={"name": "e2e-delete-me", "hostname": "delete-me.e2e.local"})
    assert r.status_code == 201
    kiosk_id = r.json()["id"]
    r = api.delete(f"/kiosks/{kiosk_id}")
    assert r.status_code == 204
    # Confirm it's gone
    r = api.get(f"/kiosks/{kiosk_id}")
    assert r.status_code == 404


def test_send_valid_command(api: httpx.Client, test_kiosk: dict):
    r = api.post(f"/kiosks/{test_kiosk['id']}/command", json={"command": "reload"})
    assert r.status_code == 204


def test_send_invalid_command_returns_400(api: httpx.Client, test_kiosk: dict):
    r = api.post(f"/kiosks/{test_kiosk['id']}/command", json={"command": "explode"})
    assert r.status_code == 400


def test_navigate(api: httpx.Client, test_kiosk: dict):
    r = api.post(
        f"/kiosks/{test_kiosk['id']}/navigate",
        json={"url": "https://example.com"},
    )
    assert r.status_code == 204


def test_command_log_returns_200(api: httpx.Client, test_kiosk: dict):
    r = api.get(f"/kiosks/{test_kiosk['id']}/command-log")
    assert r.status_code == 200
    assert "x-total-count" in r.headers
