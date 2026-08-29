"""Open tabs must never hold two copies of the same page.

_close_duplicate_tabs keeps one tab per (normalized) URL — the active one, else
the oldest — and closes the rest. It stays out of a running playlist's way but
runs under a tab cycle. Boot restore and navigate_tab also can't reintroduce
duplicates.
"""

from unittest.mock import MagicMock, patch

from kio_agent import commands, runtime
from kio_agent.agent import KioAgent


def make_agent() -> KioAgent:
    return KioAgent(
        {
            "kiosk_id": "12345678-0000-0000-0000-000000000000",
            "api_url": "http://api.test",
            "api_token": "kio_test",
            "mqtt_host": "",
            "mqtt_port": 1883,
            "topic_prefix": "kio/test",
            "features": [],
            "start_url": "https://start.example",
        }
    )


def _dedupe(agent, tabs):
    """Run _close_duplicate_tabs against a fake tab list; return closed tab ids."""
    with (
        patch("kio_agent.agent._get_tabs", return_value=tabs),
        patch("kio_agent.agent._close_tab") as close,
        patch("kio_agent.agent._report_command"),
    ):
        n = agent._close_duplicate_tabs()
    closed = [c.args[0] for c in close.call_args_list]
    assert n == len(closed)
    return closed


def test_keeps_active_tab_closes_newer_duplicates():
    tabs = [
        {"id": "old", "url": "https://a.example/", "active": False, "age_seconds": 900},
        {"id": "cur", "url": "https://a.example/", "active": True, "age_seconds": 30},
        {"id": "new", "url": "https://a.example/", "active": False, "age_seconds": 5},
        {"id": "other", "url": "https://b.example/", "active": False, "age_seconds": 100},
    ]
    assert sorted(_dedupe(make_agent(), tabs)) == ["new", "old"]


def test_keeps_oldest_when_none_active():
    tabs = [
        {"id": "young", "url": "https://a.example/", "active": False, "age_seconds": 5},
        {"id": "old", "url": "https://a.example/", "active": False, "age_seconds": 500},
    ]
    assert _dedupe(make_agent(), tabs) == ["young"]


def test_fragment_and_trailing_slash_are_the_same_page():
    tabs = [
        {"id": "T1", "url": "https://a.example/page", "active": True, "age_seconds": 100},
        {"id": "T2", "url": "https://a.example/page/", "active": False, "age_seconds": 50},
        {"id": "T3", "url": "https://a.example/page#top", "active": False, "age_seconds": 20},
        {"id": "T4", "url": "https://a.example/page?x=1", "active": False, "age_seconds": 10},
    ]
    # Query strings denote a different page and survive.
    assert sorted(_dedupe(make_agent(), tabs)) == ["T2", "T3"]


def test_distinct_pages_untouched():
    tabs = [
        {"id": "T1", "url": "https://a.example/", "active": True, "age_seconds": 10},
        {"id": "T2", "url": "https://b.example/", "active": False, "age_seconds": 10},
    ]
    assert _dedupe(make_agent(), tabs) == []


def test_skipped_while_playlist_runs():
    agent = make_agent()
    agent._player = MagicMock()
    tabs = [
        {"id": "T1", "url": "https://a.example/", "active": True, "age_seconds": 10},
        {"id": "T2", "url": "https://a.example/", "active": False, "age_seconds": 5},
    ]
    assert _dedupe(agent, tabs) == []


def test_runs_under_a_tab_cycle():
    """A tab cycle re-reads live tabs each rotation, so duplicates are safe to close
    — and a kiosk may cycle for days, so cleanup must not pause for it."""
    agent = make_agent()
    agent._cycler = MagicMock()
    tabs = [
        {"id": "T1", "url": "https://a.example/", "active": True, "age_seconds": 10},
        {"id": "T2", "url": "https://a.example/", "active": False, "age_seconds": 5},
    ]
    assert _dedupe(agent, tabs) == ["T2"]


def test_restore_collapses_duplicate_saved_tabs():
    """A snapshot carrying the same page twice restores it once, focused on the
    entry that was active."""
    agent = make_agent()
    saved = [
        {"url": "https://a.example/", "active": False},
        {"url": "https://b.example/", "active": False},
        {"url": "https://a.example/", "active": True},
    ]
    start_tab = [{"id": "S1", "url": "https://start.example", "active": True}]
    with (
        patch("kio_agent.agent._wait_for_chromium", return_value=True),
        patch("kio_agent.agent._get_tabs", return_value=start_tab),
        patch("kio_agent.agent.navigate") as nav,
        patch("kio_agent.agent._get_tab", return_value={"id": "S1"}),
        patch("kio_agent.agent._open_tab", return_value={"id": "N1"}) as open_tab,
        patch("kio_agent.agent.requests.get") as activate,
    ):
        assert agent._restore_tabs(saved) is True
    nav.assert_called_once_with("https://a.example/")
    open_tab.assert_called_once_with("https://b.example/")
    assert "/json/activate/S1" in activate.call_args.args[0]


def test_restore_matches_surviving_tabs_by_normalized_url():
    """Daemon-only restart: a live tab that gained a fragment / trailing slash
    still counts as the saved page — no second copy is opened."""
    agent = make_agent()
    saved = [{"url": "https://a.example/page", "active": True}]
    live = [{"id": "T1", "url": "https://a.example/page/#section", "active": True}]
    with (
        patch("kio_agent.agent._wait_for_chromium", return_value=True),
        patch("kio_agent.agent._get_tabs", return_value=live),
        patch("kio_agent.agent.navigate") as nav,
        patch("kio_agent.agent._open_tab") as open_tab,
        patch("kio_agent.agent.requests.get") as activate,
    ):
        assert agent._restore_tabs(saved) is True
    nav.assert_not_called()
    open_tab.assert_not_called()
    assert "/json/activate/T1" in activate.call_args.args[0]


def test_navigate_tab_dedupes_afterwards(monkeypatch):
    agent = MagicMock()
    monkeypatch.setattr(runtime, "agent", agent)
    fake_requests = MagicMock()
    fake_requests.get.return_value.json.return_value = [{"id": "T2", "type": "page", "url": "https://x"}]
    monkeypatch.setattr(commands, "requests", fake_requests)
    monkeypatch.setattr(commands, "_cdp_call", MagicMock())
    monkeypatch.setattr(commands, "_report_command", MagicMock())
    assert commands._cmd_navigate_tab({"tab_id": "T2", "url": "https://a.example/"}, None) is True
    agent._close_duplicate_tabs.assert_called_once()
