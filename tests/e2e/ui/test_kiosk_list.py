from playwright.sync_api import Page, expect


def test_kiosk_list_heading_visible(logged_in_page: Page):
    expect(logged_in_page.get_by_role("heading", name="Kiosks")).to_be_visible()


def test_add_kiosk_button_present(logged_in_page: Page):
    expect(logged_in_page.get_by_role("button", name="+ Add Kiosk")).to_be_visible()


def test_clicking_add_opens_modal(logged_in_page: Page):
    logged_in_page.get_by_role("button", name="+ Add Kiosk").click()
    expect(logged_in_page.get_by_role("heading", name="Add Kiosk")).to_be_visible()
    # Dismiss
    logged_in_page.get_by_role("button", name="Cancel").click()
    expect(logged_in_page.get_by_role("heading", name="Add Kiosk")).not_to_be_visible()


def test_kiosk_row_navigates_to_detail(logged_in_page: Page, ui_url: str):
    # There must be at least one kiosk in the environment for this to work.
    # Skip gracefully when the table is empty rather than failing.
    rows = logged_in_page.locator("table tbody tr")
    if rows.count() == 0:
        import pytest
        pytest.skip("No kiosks in environment — cannot test row navigation")
    rows.first.click()
    expect(logged_in_page).to_have_url(f"{ui_url}/kiosks/**", timeout=5_000)
