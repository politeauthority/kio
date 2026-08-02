"""Boot-time resume: state-carrying heartbeats are gated until resume has read
the previous run's state back from the API, tab cycling restarts after a tab
restore, and tabs that survived a daemon-only restart are reused, not duplicated.
"""

from unittest.mock import MagicMock, patch

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


def _heartbeat_payload(agent, **kwargs) -> dict:
    """Run _post_heartbeat with I/O stubbed and return the JSON it posted."""
    with (
        patch("kio_agent.agent.get_current_url", return_value="https://a.example"),
        patch("kio_agent.agent._get_tabs", return_value=[{"url": "https://a.example", "active": True}]),
        patch("kio_agent.agent.requests.post") as post,
    ):
        post.return_value.status_code = 204
        agent._post_heartbeat(**kwargs)
    return post.call_args.kwargs["json"]


STATE_KEYS = ("browser_tabs", "playlist_state", "tab_cycle_state")


def test_heartbeat_omits_state_before_resume():
    payload = _heartbeat_payload(make_agent())
    for key in STATE_KEYS:
        assert key not in payload


def test_heartbeat_carries_state_after_resume():
    agent = make_agent()
    agent._report_state = True
    payload = _heartbeat_payload(agent)
    assert payload["browser_tabs"] == [{"url": "https://a.example", "active": True}]
    assert payload["playlist_state"] is None
    assert payload["tab_cycle_state"] is None


def test_offline_heartbeat_omits_state():
    agent = make_agent()
    agent._report_state = True
    payload = _heartbeat_payload(agent, online=False)
    for key in STATE_KEYS:
        assert key not in payload


def test_resume_retries_on_fetch_failure_without_enabling_state():
    """API unreachable at boot: schedule a retry, keep state reporting off."""
    agent = make_agent()
    with (
        patch("kio_agent.agent.requests.get", side_effect=OSError("api down")),
        patch("kio_agent.agent.threading.Timer") as timer,
    ):
        agent._resume_state()
    assert agent._report_state is False
    timer.assert_called_once_with(agent.RESUME_RETRY_SECONDS, agent._resume_state, args=(1,))
    timer.return_value.start.assert_called_once()


def test_resume_gives_up_after_max_attempts():
    agent = make_agent()
    with (
        patch("kio_agent.agent.requests.get", side_effect=OSError("api down")),
        patch("kio_agent.agent.threading.Timer") as timer,
    ):
        agent._resume_state(_attempt=agent.RESUME_RETRIES)
    timer.assert_not_called()
    assert agent._report_state is True


def test_resume_retries_when_chromium_not_ready():
    agent = make_agent()
    resp = MagicMock(status_code=200)
    resp.json.return_value = {
        "playlist": None,
        "tabs": [{"url": "https://a.example", "active": True}],
        "tab_cycle": None,
    }
    with (
        patch("kio_agent.agent.requests.get", return_value=resp),
        patch("kio_agent.agent._wait_for_chromium", return_value=False),
        patch("kio_agent.agent.threading.Timer") as timer,
    ):
        agent._resume_state()
    assert agent._report_state is False
    timer.assert_called_once()


def test_resume_skips_when_playback_already_live():
    """A retry must not stomp a playlist/cycle an operator started meanwhile."""
    agent = make_agent()
    agent._player = MagicMock()
    with patch("kio_agent.agent.requests.get") as get:
        agent._resume_state()
    get.assert_not_called()
    assert agent._report_state is True


def test_suspend_state_reporting_reenables_if_still_alive():
    """Reboot-freeze guard: if the reboot never happens, reporting self-heals."""
    import time

    agent = make_agent()
    agent._report_state = True
    agent._suspend_state_reporting(reenable_after=0.05)
    assert agent._report_state is False
    time.sleep(0.2)
    assert agent._report_state is True


def test_resume_restarts_tab_cycle_after_tab_restore():
    agent = make_agent()
    resp = MagicMock(status_code=200)
    resp.json.return_value = {
        "playlist": None,
        "tabs": [{"url": "https://a.example", "active": True}],
        "tab_cycle": {"interval_seconds": 90, "tab_order": ["https://a.example", 7]},
    }
    with (
        patch("kio_agent.agent.requests.get", return_value=resp),
        patch("kio_agent.agent._wait_for_chromium", return_value=True),
        patch.object(agent, "_restore_tabs", return_value=True),
        patch.object(agent, "_start_tab_cycle") as start_cycle,
    ):
        agent._resume_state()
    start_cycle.assert_called_once_with(90, tab_order=["https://a.example"])


def test_resume_no_cycle_start_when_tabs_not_restored():
    agent = make_agent()
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"playlist": None, "tabs": [], "tab_cycle": {"interval_seconds": 90}}
    with (
        patch("kio_agent.agent.requests.get", return_value=resp),
        patch.object(agent, "_restore_tabs", return_value=False),
        patch.object(agent, "_start_tab_cycle") as start_cycle,
        patch.object(agent, "_show_default_page"),
    ):
        agent._resume_state()
    start_cycle.assert_not_called()


def test_restore_tabs_reuses_surviving_tabs():
    """Daemon-only restart: Chromium still has the tabs — no navigate/open calls."""
    agent = make_agent()
    saved = [
        {"url": "https://a.example", "active": False},
        {"url": "https://b.example", "active": True},
    ]
    live = [
        {"id": "T1", "url": "https://a.example", "active": True},
        {"id": "T2", "url": "https://b.example", "active": False},
    ]
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
    # Focus returns to the previously active tab (T2).
    assert "/json/activate/T2" in activate.call_args.args[0]


def test_restore_tabs_opens_missing_on_fresh_boot():
    """Fresh boot: only browser-start's tab exists — first URL reuses it, rest open."""
    agent = make_agent()
    saved = [
        {"url": "https://a.example", "active": True},
        {"url": "https://b.example", "active": False},
    ]
    start_tab = [{"id": "S1", "url": "https://start.example", "active": True}]
    with (
        patch("kio_agent.agent._wait_for_chromium", return_value=True),
        patch("kio_agent.agent._get_tabs", return_value=start_tab),
        patch("kio_agent.agent.navigate") as nav,
        patch("kio_agent.agent._get_tab", return_value={"id": "S1"}),
        patch("kio_agent.agent._open_tab", return_value={"id": "N1"}) as open_tab,
        patch("kio_agent.agent.requests.get"),
    ):
        assert agent._restore_tabs(saved) is True
    nav.assert_called_once_with("https://a.example")
    open_tab.assert_called_once_with("https://b.example")
