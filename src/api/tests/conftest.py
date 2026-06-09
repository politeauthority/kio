import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest_asyncio
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.auth import require_dashboard_auth
from app.database import get_session
from app.deps import get_node_kiosk
from app.routers import agent, agent_settings, auth, event_logs, kiosks, playlists, saved_urls, tokens


def _make_test_app() -> FastAPI:
    """Minimal FastAPI app without the lifespan for testing."""
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


_test_app = _make_test_app()


def make_kiosk(**kwargs) -> SimpleNamespace:
    """Return a SimpleNamespace that satisfies KioskRead serialization."""
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=uuid.uuid4(),
        name="Test Kiosk",
        hostname="test.local",
        current_url=None,
        status="unknown",
        last_seen=None,
        features=[],
        device_type=None,
        ip_address=None,
        current_input=None,
        display_on=None,
        agent_version=None,
        playlist_id=None,
        meta={},
        browser_flags=[],
        browser_tabs=[],
        created_at=now,
        updated_at=now,
        meta_rows=[],
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def make_playlist(**kwargs) -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=uuid.uuid4(),
        name="Test Playlist",
        description=None,
        created_at=now,
        updated_at=now,
        items=[],
        item_count=0,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def make_saved_url(**kwargs) -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=uuid.uuid4(),
        name="Example",
        url="https://example.com",
        description=None,
        created_at=now,
        updated_at=now,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_mock_session():
    """A MagicMock session whose async methods are properly awaitable.

    Defaults: execute returns None from scalar_one_or_none (no row found),
    0 from scalar_one, and [] from scalars().all().  refresh populates
    server-side timestamp fields (updated_at, created_at, sent_at) so that
    Pydantic response validation succeeds for freshly-created ORM objects.
    """
    s = MagicMock()

    _result = MagicMock()
    _result.scalar_one.return_value = 0
    _result.scalar_one_or_none.return_value = None
    _result.scalars.return_value.all.return_value = []
    _result.all.return_value = []  # multi-column selects (e.g. event-log joins)
    s.execute = AsyncMock(return_value=_result)

    s.commit = AsyncMock()
    s.delete = AsyncMock()
    s.flush = AsyncMock()
    s.get = AsyncMock(return_value=None)
    s.add = MagicMock()

    async def _refresh(obj):
        now = datetime.now(timezone.utc)
        for field in ("updated_at", "created_at", "sent_at", "agent_at"):
            if hasattr(obj, field) and getattr(obj, field) is None:
                setattr(obj, field, now)
        if hasattr(obj, "id") and getattr(obj, "id") is None:
            setattr(obj, "id", uuid.uuid4())

    s.refresh = AsyncMock(side_effect=_refresh)
    return s


@pytest_asyncio.fixture
async def client():
    """Dashboard client with auth bypassed and a mock DB session."""
    mock_session = _make_mock_session()

    async def _override_session():
        yield mock_session

    _test_app.dependency_overrides[get_session] = _override_session
    _test_app.dependency_overrides[require_dashboard_auth] = lambda: "test-user"

    async with AsyncClient(transport=ASGITransport(app=_test_app), base_url="http://test") as ac:
        yield ac

    _test_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def agent_client():
    """Agent client with a fixed kiosk injected via get_node_kiosk override."""
    kiosk = make_kiosk(name="agent-kiosk", hostname="agent.local", status="online")
    mock_session = _make_mock_session()

    async def _override_session():
        yield mock_session

    async def _override_node_kiosk():
        return kiosk

    _test_app.dependency_overrides[get_session] = _override_session
    _test_app.dependency_overrides[get_node_kiosk] = _override_node_kiosk

    with patch("app.routers.agent.notify_subscribers"):
        async with AsyncClient(transport=ASGITransport(app=_test_app), base_url="http://test") as ac:
            yield ac, kiosk, mock_session

    _test_app.dependency_overrides.clear()
