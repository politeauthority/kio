"""Shared fixtures for kio e2e tests.

Configuration via environment variables (or tests/e2e/.env):
  KIO_API_URL      API base URL  (default: http://api.kio-dev.example.local)
  KIO_UI_URL       UI base URL   (default: http://kio-dev.example.local)
  KIO_USERNAME     login username
  KIO_PASSWORD     login password
"""
import os
import uuid

import httpx
import pytest
from dotenv import load_dotenv
from playwright.sync_api import Page

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

_API_URL = os.environ.get("KIO_API_URL", "http://api.kio-dev.example.local").rstrip("/")
_UI_URL = os.environ.get("KIO_UI_URL", "http://kio-dev.example.local").rstrip("/")
_USERNAME = os.environ.get("KIO_USERNAME", "")
_PASSWORD = os.environ.get("KIO_PASSWORD", "")


# ---------------------------------------------------------------------------
# API fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def api_url() -> str:
    return _API_URL


@pytest.fixture(scope="session")
def auth_token(api_url: str) -> str:
    assert _USERNAME and _PASSWORD, (
        "KIO_USERNAME and KIO_PASSWORD must be set (or defined in tests/e2e/.env)"
    )
    r = httpx.post(f"{api_url}/auth/login", json={"username": _USERNAME, "password": _PASSWORD})
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def api(api_url: str, auth_token: str) -> httpx.Client:
    """Authenticated httpx client for the API."""
    with httpx.Client(
        base_url=api_url,
        headers={"Authorization": f"Bearer {auth_token}"},
        timeout=10.0,
    ) as client:
        yield client


@pytest.fixture
def test_kiosk(api: httpx.Client):
    """Create a scratch kiosk for a test and delete it after."""
    name = f"e2e-{uuid.uuid4().hex[:8]}"
    r = api.post("/kiosks", json={"name": name, "hostname": f"{name}.e2e.local"})
    assert r.status_code == 201, f"Could not create test kiosk: {r.text}"
    kiosk = r.json()
    yield kiosk
    api.delete(f"/kiosks/{kiosk['id']}")


# ---------------------------------------------------------------------------
# UI fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def ui_url() -> str:
    return _UI_URL


@pytest.fixture
def logged_in_page(page: Page, ui_url: str) -> Page:
    """Navigate to the app and log in; yields a page on the kiosk list."""
    assert _USERNAME and _PASSWORD, (
        "KIO_USERNAME and KIO_PASSWORD must be set (or defined in tests/e2e/.env)"
    )
    page.goto(f"{ui_url}/login")
    page.locator('input[autocomplete="username"]').fill(_USERNAME)
    page.locator('input[type="password"]').fill(_PASSWORD)
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url(f"{ui_url}/", timeout=10_000)
    return page
