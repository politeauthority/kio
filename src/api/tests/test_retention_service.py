"""Server-side retention purges: what they delete and what they deliberately keep."""

from unittest.mock import AsyncMock, MagicMock

from app.services import retention_service as rs


def _session(rowcounts):
    session = MagicMock()
    results = [MagicMock(rowcount=n) for n in rowcounts]
    session.execute = AsyncMock(side_effect=results)
    session.commit = AsyncMock()
    return session


async def test_purge_command_logs_deletes_by_sent_at():
    session = _session([7])
    assert await rs.purge_command_logs(session, 7) == 7
    stmt = session.execute.call_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "DELETE FROM command_logs" in sql and "sent_at <" in sql


async def test_purge_hardware_logs_keeps_each_kiosks_newest_row():
    session = _session([3])
    assert await rs.purge_hardware_detect_logs(session, 30) == 3
    stmt = session.execute.call_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "DELETE FROM hardware_detect_logs" in sql
    assert "detected_at <" in sql
    # The newest-per-kiosk subquery is excluded from the delete.
    assert "NOT IN" in sql and "max(hardware_detect_logs.detected_at)" in sql


async def test_run_retention_commits_once_and_reports_both():
    session = _session([2, 5])
    removed = await rs.run_retention(session, {"event_log_purge_days": 7, "hardware_log_purge_days": 30})
    assert removed == {"command_logs": 2, "hardware_detect_logs": 5}
    session.commit.assert_awaited_once()
