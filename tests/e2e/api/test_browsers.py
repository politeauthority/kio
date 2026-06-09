"""Browser tab API endpoints — tests only verify the API accepts/rejects correctly.
The actual CDP side effects require a live Pi agent to confirm.
"""
import httpx


def test_list_browser_tabs_returns_list(api: httpx.Client, test_kiosk: dict):
    r = api.get(f"/kiosks/{test_kiosk['id']}/browsers")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_open_tab_returns_204(api: httpx.Client, test_kiosk: dict):
    r = api.post(
        f"/kiosks/{test_kiosk['id']}/browsers",
        json={"url": "https://example.com"},
    )
    assert r.status_code == 204


def test_close_tab_returns_204(api: httpx.Client, test_kiosk: dict):
    r = api.delete(f"/kiosks/{test_kiosk['id']}/browsers/fake-tab-id")
    assert r.status_code == 204


def test_activate_tab_returns_204(api: httpx.Client, test_kiosk: dict):
    r = api.post(f"/kiosks/{test_kiosk['id']}/browsers/fake-tab-id/activate")
    assert r.status_code == 204


def test_navigate_tab_returns_204(api: httpx.Client, test_kiosk: dict):
    r = api.post(
        f"/kiosks/{test_kiosk['id']}/browsers/fake-tab-id/navigate",
        json={"url": "https://example.com"},
    )
    assert r.status_code == 204


def test_browser_tab_endpoints_on_missing_kiosk(api: httpx.Client):
    missing_id = "00000000-0000-0000-0000-000000000000"
    assert api.get(f"/kiosks/{missing_id}/browsers").status_code == 404
    assert api.post(f"/kiosks/{missing_id}/browsers", json={"url": "https://x.com"}).status_code == 404
