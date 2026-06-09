import os

from playwright.sync_api import Page, expect


_USERNAME = os.environ.get("KIO_USERNAME", "")
_PASSWORD = os.environ.get("KIO_PASSWORD", "")


def test_login_page_loads(page: Page, ui_url: str):
    page.goto(f"{ui_url}/login")
    expect(page.locator('input[autocomplete="username"]')).to_be_visible()
    expect(page.locator('input[type="password"]')).to_be_visible()
    expect(page.get_by_role("button", name="Sign in")).to_be_visible()


def test_login_invalid_shows_error(page: Page, ui_url: str):
    page.goto(f"{ui_url}/login")
    page.locator('input[autocomplete="username"]').fill("wrong")
    page.locator('input[type="password"]').fill("wrong")
    page.get_by_role("button", name="Sign in").click()
    expect(page.locator(".login-error")).to_be_visible(timeout=5_000)
    expect(page.locator(".login-error")).to_contain_text("Invalid")


def test_login_valid_redirects_to_kiosk_list(logged_in_page: Page, ui_url: str):
    expect(logged_in_page).to_have_url(f"{ui_url}/")
    expect(logged_in_page.get_by_role("heading", name="Kiosks")).to_be_visible()
