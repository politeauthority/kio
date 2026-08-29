"""Tests for the pure ordering/state logic of TabCycler and PlaylistPlayer.

These exercise construction and the deterministic helpers only; the threaded run
loops and CDP I/O are not started.
"""

from kio_agent.playlist import PlaylistPlayer, TabCycler


def _tab(tid, url, active=False):
    return {"id": tid, "url": url, "active": active}


# --- TabCycler._ordered_tabs ------------------------------------------------


def test_ordered_tabs_without_order_returns_input_unchanged():
    cycler = TabCycler(10)
    tabs = [_tab("a", "http://x"), _tab("b", "http://y")]
    assert cycler._ordered_tabs(tabs) == tabs


def test_ordered_tabs_sorts_by_saved_url_order():
    cycler = TabCycler(10, tab_order=["http://b", "http://a"])
    tabs = [_tab("1", "http://a"), _tab("2", "http://b")]
    ordered = [t["id"] for t in cycler._ordered_tabs(tabs)]
    assert ordered == ["2", "1"]  # b before a per saved order


def test_ordered_tabs_appends_unknown_urls_at_end():
    cycler = TabCycler(10, tab_order=["http://a"])
    tabs = [_tab("u", "http://unknown"), _tab("a", "http://a")]
    ordered = [t["id"] for t in cycler._ordered_tabs(tabs)]
    assert ordered == ["a", "u"]  # known first, unknown keeps trailing position


def test_tab_cycler_state_includes_tab_order():
    cycler = TabCycler(90, tab_order=["https://a.example", "https://b.example"])
    state = cycler.current_state()
    assert state["interval_seconds"] == 90
    assert state["tab_order"] == ["https://a.example", "https://b.example"]


def test_tab_cycler_filters_non_string_order_entries():
    cycler = TabCycler(10, tab_order=["http://a", None, 5, "http://b"])
    assert cycler._tab_order == ["http://a", "http://b"]


def test_tab_cycler_interval_floor_is_one():
    assert TabCycler(0)._interval == 1
    assert TabCycler(-5)._interval == 1
    assert TabCycler(12)._interval == 12


# --- PlaylistPlayer.current_state -------------------------------------------


def test_playlist_current_state_before_start():
    items = [{"url": "http://a", "duration_seconds": 5}, {"url": "http://b", "duration_seconds": 5}]
    player = PlaylistPlayer("pl1", items)
    state = player.current_state()
    assert state == {"idx": 0, "started_at": None, "total": 2, "paused": False}


def test_playlist_current_state_reports_started_at_when_set():
    items = [{"url": "http://a", "duration_seconds": 5}]
    player = PlaylistPlayer("pl1", items)
    player._item_started_at = 1_700_000_000.0
    player._current_idx = 0
    state = player.current_state()
    assert state["idx"] == 0
    assert state["total"] == 1
    assert state["started_at"] is not None
    assert state["started_at"].startswith("20")  # ISO-8601 timestamp


def test_playlist_name_defaults_to_id():
    player = PlaylistPlayer("pl1", [])
    assert player._playlist_name == "pl1"


def test_playlist_name_used_when_given():
    player = PlaylistPlayer("pl1", [], playlist_name="Lobby")
    assert player._playlist_name == "Lobby"


# --- PlaylistPlayer pause / resume --------------------------------------------


def _player_with_tabs(n=2):
    """A player whose run loop can be driven without CDP: tabs are fakes and
    tab activation is a no-op."""
    items = [{"url": f"http://{i}", "duration_seconds": 0.05} for i in range(n)]
    player = PlaylistPlayer("pl1", items, refresh_seconds=0)
    player._tabs = [{"id": f"t{i}", "url": f"http://{i}"} for i in range(n)]
    return player


def test_start_paused_is_reflected_in_state():
    player = PlaylistPlayer("pl1", [{"url": "http://a", "duration_seconds": 5}], start_paused=True)
    assert player.paused is True
    assert player.current_state()["paused"] is True


def test_pause_holds_the_current_item(monkeypatch):
    import time as _time

    from kio_agent import playlist as mod

    monkeypatch.setattr(mod, "_activate_tab", lambda tab_id: True)
    monkeypatch.setattr(mod, "_close_tab", lambda tab_id: None)
    player = _player_with_tabs(3)
    player.pause()  # queued before the loop starts: takes effect on the first item
    player._thread.start()
    _time.sleep(0.3)  # several durations' worth — a playing loop would have advanced
    assert player.paused is True
    assert player.current_state()["idx"] == 0
    player.stop()


def test_resume_advances_again(monkeypatch):
    import time as _time

    from kio_agent import playlist as mod

    monkeypatch.setattr(mod, "_activate_tab", lambda tab_id: True)
    monkeypatch.setattr(mod, "_close_tab", lambda tab_id: None)
    player = _player_with_tabs(3)
    player.pause()
    player._thread.start()
    _time.sleep(0.15)
    player.resume()
    _time.sleep(0.3)
    assert player.paused is False
    assert player.current_state()["idx"] != 0
    player.stop()


def test_goto_while_paused_moves_but_stays_paused(monkeypatch):
    import time as _time

    from kio_agent import playlist as mod

    monkeypatch.setattr(mod, "_activate_tab", lambda tab_id: True)
    monkeypatch.setattr(mod, "_close_tab", lambda tab_id: None)
    monkeypatch.setattr(mod, "_report_command", lambda *a, **k: None)
    player = _player_with_tabs(3)
    player.pause()
    player._thread.start()
    _time.sleep(0.1)
    player.goto(2)
    _time.sleep(0.3)
    assert player.current_state()["idx"] == 2
    assert player.paused is True
    player.stop()
