"""Router tests for /saved-urls — verifies HTTP layer behaviour with a mocked session."""

import uuid

import pytest

from tests.conftest import make_saved_url


# ---------------------------------------------------------------------------
# GET /saved-urls
# ---------------------------------------------------------------------------


async def test_list_saved_urls_returns_200(client):
    r = await client.get("/saved-urls")
    assert r.status_code == 200
    assert r.json() == []


async def test_list_saved_urls_with_query_param_returns_200(client):
    r = await client.get("/saved-urls?q=dashboard")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ---------------------------------------------------------------------------
# POST /saved-urls
# ---------------------------------------------------------------------------


async def test_create_saved_url_missing_name_returns_422(client):
    r = await client.post("/saved-urls", json={"url": "https://example.com"})
    assert r.status_code == 422


async def test_create_saved_url_missing_url_returns_422(client):
    r = await client.post("/saved-urls", json={"name": "Example"})
    assert r.status_code == 422


async def test_create_saved_url_empty_body_returns_422(client):
    r = await client.post("/saved-urls", json={})
    assert r.status_code == 422


async def test_create_saved_url_valid_returns_201(client):
    r = await client.post(
        "/saved-urls",
        json={"name": "Dashboard", "url": "https://dash.example.com", "description": "Main board"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Dashboard"
    assert body["url"] == "https://dash.example.com"
    assert body["description"] == "Main board"
    assert "id" in body


async def test_create_saved_url_description_optional(client):
    r = await client.post("/saved-urls", json={"name": "Minimal", "url": "https://minimal.example.com"})
    assert r.status_code == 201
    assert r.json()["description"] is None


# ---------------------------------------------------------------------------
# GET /saved-urls/{id}
# ---------------------------------------------------------------------------


async def test_get_saved_url_not_found(client):
    r = await client.get(f"/saved-urls/{uuid.uuid4()}")
    assert r.status_code == 404


async def test_get_saved_url_found(client, mock_session_with_url):
    saved, client_ = mock_session_with_url
    r = await client_.get(f"/saved-urls/{saved.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == saved.name
    assert body["url"] == saved.url


# ---------------------------------------------------------------------------
# PUT /saved-urls/{id}
# ---------------------------------------------------------------------------


async def test_update_saved_url_not_found(client):
    r = await client.put(
        f"/saved-urls/{uuid.uuid4()}",
        json={"name": "Updated", "url": "https://updated.example.com"},
    )
    assert r.status_code == 404


async def test_update_saved_url_missing_name_returns_422(client):
    r = await client.put(
        f"/saved-urls/{uuid.uuid4()}",
        json={"url": "https://example.com"},
    )
    assert r.status_code == 422


async def test_update_saved_url_missing_url_returns_422(client):
    r = await client.put(
        f"/saved-urls/{uuid.uuid4()}",
        json={"name": "Updated"},
    )
    assert r.status_code == 422


async def test_update_saved_url_found(client, mock_session_with_url):
    saved, client_ = mock_session_with_url
    r = await client_.put(
        f"/saved-urls/{saved.id}",
        json={"name": "New Name", "url": "https://new.example.com", "description": "Updated desc"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "New Name"
    assert body["url"] == "https://new.example.com"


# ---------------------------------------------------------------------------
# DELETE /saved-urls/{id}
# ---------------------------------------------------------------------------


async def test_delete_saved_url_not_found(client):
    r = await client.delete(f"/saved-urls/{uuid.uuid4()}")
    assert r.status_code == 404


async def test_delete_saved_url_found(client, mock_session_with_url):
    saved, client_ = mock_session_with_url
    r = await client_.delete(f"/saved-urls/{saved.id}")
    assert r.status_code == 204


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def mock_session_with_url(client):
    """Yield a (saved_url, client) pair where session.get returns a real-ish object."""
    from datetime import datetime, timezone
    from unittest.mock import AsyncMock, MagicMock

    from app.models.saved_url import SavedUrl
    from app.database import get_session
    from app.auth import require_dashboard_auth
    from fastapi import Depends, FastAPI
    from httpx import ASGITransport, AsyncClient
    from app.routers import agent, agent_settings, auth, event_logs, kiosks, playlists, saved_urls, tokens

    now = datetime.now(timezone.utc)
    url_obj = SavedUrl(name="Test URL", url="https://test.example.com", description="desc")
    url_obj.id = __import__("uuid").uuid4()
    url_obj.created_at = now
    url_obj.updated_at = now

    mock_session = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.delete = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.get = AsyncMock(return_value=url_obj)

    async def _refresh(obj):
        if not hasattr(obj, "created_at") or obj.created_at is None:
            obj.created_at = now
        if not hasattr(obj, "updated_at") or obj.updated_at is None:
            obj.updated_at = now

    mock_session.refresh = AsyncMock(side_effect=_refresh)

    _result = MagicMock()
    _result.scalar_one_or_none.return_value = None
    _result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=_result)

    def _make_app() -> FastAPI:
        app = FastAPI()
        _auth = [Depends(require_dashboard_auth)]
        app.include_router(kiosks.router, dependencies=_auth)
        app.include_router(tokens.router, dependencies=_auth)
        app.include_router(auth.router)
        app.include_router(agent.router)
        app.include_router(playlists.router, dependencies=_auth)
        app.include_router(event_logs.router, dependencies=_auth)
        app.include_router(agent_settings.router, dependencies=_auth)
        app.include_router(saved_urls.router, dependencies=_auth)
        return app

    app = _make_app()
    app.dependency_overrides[get_session] = lambda: (_ for _ in ()).__next__  # replaced below
    app.dependency_overrides[require_dashboard_auth] = lambda: "test-user"

    async def _override_session():
        yield mock_session

    app.dependency_overrides[get_session] = _override_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield url_obj, ac
