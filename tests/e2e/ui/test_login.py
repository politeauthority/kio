import os

from playwright.sync_api import Page, expect


_USERNAME = os.environ.get("KIO_USERNAME", "")
_PASSWORD = os.environ.get("KIO_PASSWORD", "")


def test_login_page_loads(page: Page, ui_url: str):
    page.goto(f"{ui_url}/login")
    expect(page.locator('input[autocomplete="username"]')).to_be_visible()
    expect(page.locator('input[type="password"]')).to_be_visible()
    expect(page.get_by_role("button", name="Sign in", exact=True)).to_be_visible()


def test_login_invalid_shows_error(page: Page, ui_url: str):
    page.goto(f"{ui_url}/login")
    page.locator('input[autocomplete="username"]').fill("wrong")
    page.locator('input[type="password"]').fill("wrong")
    page.get_by_role("button", name="Sign in", exact=True).click()
    expect(page.locator(".login-error")).to_be_visible(timeout=5_000)
    expect(page.locator(".login-error")).to_contain_text("Invalid")


def test_login_valid_redirects_to_kiosk_list(logged_in_page: Page, ui_url: str):
    expect(logged_in_page).to_have_url(f"{ui_url}/")
    expect(logged_in_page.get_by_role("heading", name="Kiosks")).to_be_visible()


def test_auth_config_advertises_dev_login(api_url: str):
    """The UI decides which login options to show from this public endpoint."""
    import httpx

    r = httpx.get(f"{api_url}/auth/config", timeout=10.0)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"disabled", "oidc", "dev_login"}
    assert body["dev_login"] is True
    if body["oidc"] is not None:
        assert body["oidc"]["authority"] and body["oidc"]["client_id"]
