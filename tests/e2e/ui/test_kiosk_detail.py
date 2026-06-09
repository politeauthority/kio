"""Kiosk detail page — navigates to the first available kiosk.

All tests skip if the environment has no kiosks rather than failing.
"""
import pytest
from playwright.sync_api import Page, expect


@pytest.fixture
def detail_page(logged_in_page: Page, ui_url: str, api):
    """Navigate to the detail page of the first kiosk returned by the API."""
    kiosks = api.get("/kiosks").json()
    if not kiosks:
        pytest.skip("No kiosks in environment")
    kiosk = kiosks[0]
    logged_in_page.goto(f"{ui_url}/kiosks/{kiosk['id']}")
    logged_in_page.wait_for_load_state("networkidle")
    return logged_in_page, kiosk


def test_detail_shows_kiosk_name(detail_page):
    page, kiosk = detail_page
    expect(page.get_by_role("heading", name=kiosk["name"])).to_be_visible()


def test_detail_shows_status_badge(detail_page):
    page, _ = detail_page
    expect(page.locator(".status-badge")).to_be_visible()


def test_detail_has_commands_card(detail_page):
    page, _ = detail_page
    expect(page.locator(".card-header", has_text="Commands")).to_be_visible()


def test_detail_has_browsers_card(detail_page):
    page, _ = detail_page
    expect(page.locator(".card-header", has_text="Browsers")).to_be_visible()


def test_browsers_card_has_open_tab_input(detail_page):
    page, _ = detail_page
    # "Open new tab" form is always rendered (not conditional); scoped to the form element
    browsers_card = page.locator(".card", has=page.locator(".card-header", has_text="Browsers"))
    expect(browsers_card.locator("form").locator('input[type="url"]')).to_be_visible()


def test_detail_back_link_returns_to_list(detail_page, ui_url: str):
    page, _ = detail_page
    page.get_by_text("← All Kiosks").click()
    expect(page).to_have_url(f"{ui_url}/", timeout=5_000)
