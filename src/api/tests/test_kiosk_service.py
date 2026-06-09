"""Unit tests for app.services.kiosk_service — all DB calls are mocked."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.command_log import CommandLog
from app.models.kiosk import Kiosk
from app.schemas.kiosk import KioskCreate, KioskUpdate
from app.services import kiosk_service


def _exec_result(*, scalars=None, scalar_one=None, scalar_one_or_none=None):
    """Build a MagicMock that mimics a SQLAlchemy execute result."""
    r = MagicMock()
    r.scalars.return_value.all.return_value = scalars or []
    r.scalar_one.return_value = scalar_one
    r.scalar_one_or_none.return_value = scalar_one_or_none
    return r


def _mock_session():
    s = MagicMock()
    s.execute = AsyncMock(return_value=_exec_result())
    s.get = AsyncMock(return_value=None)
    s.add = MagicMock()
    s.delete = AsyncMock()
    s.commit = AsyncMock()
    s.refresh = AsyncMock()
    return s


def _kiosk(**kwargs):
    k = MagicMock(spec=Kiosk)
    k.id = kwargs.get("id", uuid.uuid4())
    k.name = kwargs.get("name", "Test")
    k.hostname = kwargs.get("hostname", "test.local")
    k.status = kwargs.get("status", "unknown")
    k.last_seen = kwargs.get("last_seen", None)
    k.features = kwargs.get("features", [])
    return k


# ---------------------------------------------------------------------------
# get_all
# ---------------------------------------------------------------------------


async def test_get_all_returns_ordered_kiosks():
    session = _mock_session()
    kiosks = [_kiosk(name="A"), _kiosk(name="B")]
    session.execute = AsyncMock(return_value=_exec_result(scalars=kiosks))

    result = await kiosk_service.get_all(session)

    assert list(result) == kiosks
    session.execute.assert_awaited_once()


async def test_get_all_empty():
    session = _mock_session()
    session.execute = AsyncMock(return_value=_exec_result(scalars=[]))

    result = await kiosk_service.get_all(session)

    assert list(result) == []


# ---------------------------------------------------------------------------
# get_by_id
# ---------------------------------------------------------------------------


async def test_get_by_id_found():
    session = _mock_session()
    kiosk = _kiosk()
    session.get.return_value = kiosk

    result = await kiosk_service.get_by_id(session, kiosk.id)

    session.get.assert_awaited_once_with(Kiosk, kiosk.id)
    assert result is kiosk


async def test_get_by_id_not_found():
    session = _mock_session()
    session.get.return_value = None

    result = await kiosk_service.get_by_id(session, uuid.uuid4())

    assert result is None


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


async def test_create_assigns_uuid_and_persists():
    session = _mock_session()
    data = KioskCreate(name="New Kiosk", hostname="new.local")

    await kiosk_service.create(session, data)

    session.add.assert_called_once()
    added: Kiosk = session.add.call_args[0][0]
    assert added.name == "New Kiosk"
    assert added.hostname == "new.local"
    assert added.id is not None
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once_with(added)


# ---------------------------------------------------------------------------
# update_kiosk
# ---------------------------------------------------------------------------


async def test_update_kiosk_patches_name():
    session = _mock_session()
    kiosk = _kiosk(name="Old", hostname="old.local")
    session.get.return_value = kiosk

    await kiosk_service.update_kiosk(session, kiosk.id, KioskUpdate(name="New"))

    assert kiosk.name == "New"
    assert kiosk.hostname == "old.local"  # unchanged
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once_with(kiosk)


async def test_update_kiosk_patches_hostname():
    session = _mock_session()
    kiosk = _kiosk()
    session.get.return_value = kiosk

    await kiosk_service.update_kiosk(session, kiosk.id, KioskUpdate(hostname="new.local"))

    assert kiosk.hostname == "new.local"


async def test_update_kiosk_patches_features():
    session = _mock_session()
    kiosk = _kiosk()
    session.get.return_value = kiosk

    await kiosk_service.update_kiosk(session, kiosk.id, KioskUpdate(features=["hdmi"]))

    assert kiosk.features == ["hdmi"]


async def test_update_kiosk_not_found_returns_none():
    session = _mock_session()
    session.get.return_value = None

    result = await kiosk_service.update_kiosk(session, uuid.uuid4(), KioskUpdate(name="X"))

    assert result is None
    session.commit.assert_not_awaited()


async def test_update_kiosk_none_fields_not_applied():
    session = _mock_session()
    kiosk = _kiosk(name="Keep", hostname="keep.local")
    session.get.return_value = kiosk

    # All fields None — nothing should change
    await kiosk_service.update_kiosk(session, kiosk.id, KioskUpdate())

    assert kiosk.name == "Keep"
    assert kiosk.hostname == "keep.local"


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


async def test_delete_existing_kiosk():
    session = _mock_session()
    kiosk = _kiosk()
    session.get.return_value = kiosk

    result = await kiosk_service.delete(session, kiosk.id)

    assert result is True
    session.delete.assert_awaited_once_with(kiosk)
    session.commit.assert_awaited_once()


async def test_delete_missing_kiosk():
    session = _mock_session()
    session.get.return_value = None

    result = await kiosk_service.delete(session, uuid.uuid4())

    assert result is False
    session.delete.assert_not_awaited()


# ---------------------------------------------------------------------------
# mark_offline_kiosks
# ---------------------------------------------------------------------------


async def test_mark_offline_kiosks_marks_stale_online_kiosks():
    session = _mock_session()
    stale = _kiosk(status="online")
    stale.last_seen = datetime.now(timezone.utc) - timedelta(seconds=200)

    # First execute returns the stale kiosks; second (UPDATE) returns a plain mock
    session.execute = AsyncMock(
        side_effect=[
            _exec_result(scalars=[stale]),
            MagicMock(),
        ]
    )

    with patch("app.services.kiosk_service.settings") as mock_settings:
        mock_settings.node_offline_threshold_seconds = 90
        await kiosk_service.mark_offline_kiosks(session)

    assert session.execute.await_count == 2
    session.add.assert_called_once()
    added = session.add.call_args[0][0]
    assert isinstance(added, CommandLog)
    assert added.kiosk_id == stale.id
    assert "offline" in added.command
    session.commit.assert_awaited_once()


async def test_mark_offline_kiosks_skips_already_offline():
    session = _mock_session()
    session.execute = AsyncMock(return_value=_exec_result(scalars=[]))

    with patch("app.services.kiosk_service.settings") as mock_settings:
        mock_settings.node_offline_threshold_seconds = 90
        await kiosk_service.mark_offline_kiosks(session)

    assert session.execute.await_count == 1  # only the SELECT, no UPDATE
    session.add.assert_not_called()
    session.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# update_kiosk_from_heartbeat
# ---------------------------------------------------------------------------


async def test_update_kiosk_from_heartbeat_invalid_uuid():
    """Invalid UUID string should return early without any DB interaction."""
    with patch("app.database.async_session_factory") as mock_factory:
        await kiosk_service.update_kiosk_from_heartbeat("not-a-uuid", {})
        mock_factory.assert_not_called()


async def test_update_kiosk_from_heartbeat_missing_kiosk():
    session = _mock_session()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.get = AsyncMock(return_value=None)

    with patch("app.database.async_session_factory", return_value=session):
        await kiosk_service.update_kiosk_from_heartbeat(str(uuid.uuid4()), {"online": True})

    session.commit.assert_not_awaited()


async def test_update_kiosk_from_heartbeat_updates_fields():
    session = _mock_session()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    kiosk = _kiosk(status="offline")
    session.get = AsyncMock(return_value=kiosk)

    with patch("app.database.async_session_factory", return_value=session):
        await kiosk_service.update_kiosk_from_heartbeat(
            str(kiosk.id), {"online": True, "current_url": "https://example.com"}
        )

    assert kiosk.status == "online"
    assert kiosk.current_url == "https://example.com"
    assert kiosk.last_seen is not None
    session.commit.assert_awaited_once()
