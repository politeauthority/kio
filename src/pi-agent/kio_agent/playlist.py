"""Playlist playback and tab cycling.

:class:`PlaylistPlayer` preloads every playlist URL as a background tab so each
transition is an instant tab activation (with a CSS fade-in) rather than a page
load, and refreshes tabs on a steady background cadence. :class:`TabCycler`
rotates focus through whatever tabs already exist without opening or closing any.
"""

import queue
import random
import threading
import time
from datetime import datetime, timezone

from kio_agent.cdp import (
    _activate_tab,
    _close_tab,
    _get_tabs,
    _install_fade_script,
    _open_tab,
    _reload_tab,
    _wait_for_chromium,
)
from kio_agent.constants import PLAYLIST_REFRESH_SECONDS, logger
from kio_agent.reporting import _report_command


class PlaylistPlayer:
    """Cycles through playlist items by switching between preloaded browser tabs.

    All URLs are opened as background tabs before playback begins so every
    transition is an instant tab activation rather than a page load. The
    incoming tab fades in via a visibilitychange listener installed through CDP.
    On stop, the current tab stays visible; all other preloaded tabs are closed.

    A background refresh loop reloads the tabs on a steady cadence
    (refresh_seconds) so their content stays current without reloading on every
    rotation; it reloads tabs while they're hidden to avoid a visible flash.

    Commands are delivered via an internal queue so goto() can interrupt a
    sleeping duration without polling.
    """

    def __init__(
        self,
        playlist_id: str,
        items: list[dict],
        playlist_name: str = "",
        start_idx: int = 0,
        refresh_seconds: int = PLAYLIST_REFRESH_SECONDS,
    ) -> None:
        self.playlist_id = playlist_id
        self._playlist_name = playlist_name or playlist_id
        self._items = items
        self._start_idx = start_idx
        self._refresh_seconds = refresh_seconds
        self._tabs: list[dict] = []  # ordered CDP tab dicts, one per item
        self._current_idx = 0
        self._item_started_at: float = 0.0
        self._lock = threading.Lock()
        self._cmd: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._next_refresh: dict[str, float] = {}  # tab id -> epoch time of next reload
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._refresh_thread = threading.Thread(target=self._refresh_loop, daemon=True)

    def start(self) -> None:
        self._preload()
        self._thread.start()
        if self._refresh_seconds > 0:
            self._refresh_thread.start()

    def stop(self) -> None:
        """Signal the play + refresh loops to exit, then close all background tabs."""
        self._stop_event.set()
        self._cmd.put(("stop", None))
        self._thread.join(timeout=2)
        with self._lock:
            active_id = self._tabs[self._current_idx]["id"] if self._tabs else None
            to_close = [t["id"] for t in self._tabs if t["id"] != active_id]
            self._tabs = []
        for tab_id in to_close:
            _close_tab(tab_id)

    def _next_refresh_at(self) -> float:
        """A refresh time one interval out, with ±20% jitter so tabs don't all
        reload at the same instant."""
        jitter = self._refresh_seconds * 0.2
        return time.time() + self._refresh_seconds + random.uniform(-jitter, jitter)

    def _refresh_tab(self, tab: dict) -> None:
        """Reload one tab and schedule its next refresh."""
        _reload_tab(tab)
        with self._lock:
            self._next_refresh[tab["id"]] = self._next_refresh_at()

    def _refresh_loop(self) -> None:
        """Reload each tab on its own jittered cadence so content stays fresh.

        Only background tabs are reloaded (never the visible one) so a refresh
        always lands *before* a tab becomes active and never flashes the screen;
        the visible tab is refreshed once it rotates out. A single-tab playlist has
        nothing to hide behind, so it's reloaded in place. The rotation loop also
        pre-refreshes the on-deck tab (see _run) to maximise lead time.
        """
        poll = max(2, min(15, self._refresh_seconds // 4))
        while not self._stop_event.wait(poll):
            now = time.time()
            with self._lock:
                tabs = list(self._tabs)
                active_id = tabs[self._current_idx]["id"] if tabs else None
                due = [
                    t
                    for t in tabs
                    if now >= self._next_refresh.get(t["id"], 0) and (len(tabs) <= 1 or t["id"] != active_id)
                ]
            for tab in due:
                if self._stop_event.is_set():
                    break
                self._refresh_tab(tab)

    def _prerefresh_on_deck(self, idx: int) -> None:
        """Refresh the tab that will be shown next, if it's due — giving it the
        current item's full duration to reload while still hidden."""
        if self._refresh_seconds <= 0:
            return
        with self._lock:
            n = len(self._tabs)
            if n <= 1:
                return
            on_deck = self._tabs[(idx + 1) % n]
            active_id = self._tabs[self._current_idx]["id"]
            due = time.time() >= self._next_refresh.get(on_deck["id"], 0) and on_deck["id"] != active_id
        if due:
            self._refresh_tab(on_deck)

    def goto(self, idx: int) -> None:
        """Jump to a specific playlist item by index, resetting its duration timer."""
        self._cmd.put(("goto", idx))

    def current_state(self) -> dict:
        with self._lock:
            return {
                "idx": self._current_idx,
                "started_at": (
                    datetime.fromtimestamp(self._item_started_at, tz=timezone.utc).isoformat()
                    if self._item_started_at
                    else None
                ),
                "total": len(self._items),
            }

    def _preload(self) -> None:
        # Wait for Chromium to be controllable — playback is often resumed right
        # after boot before the browser is ready, which would otherwise drop tabs.
        if not _wait_for_chromium():
            logger.warning("Playlist %s: browser not ready after wait; preload may be incomplete", self.playlist_id)
        loaded_items: list[dict] = []
        loaded_tabs: list[dict] = []
        for item in self._items:
            tab = _open_tab(item["url"])
            if tab:
                _install_fade_script(tab)
                loaded_tabs.append(tab)
                loaded_items.append(item)
        # Keep items and tabs in sync so goto indices always match
        self._items = loaded_items
        self._tabs = loaded_tabs
        # Close any pre-existing tabs (the start_url tab, leftovers from a previous
        # playlist) so only this playlist's tabs remain. Without this, tabs pile up
        # across plays — duplicates and orphans the dashboard shows as stale tabs.
        # Guard: only prune once we actually have new tabs, so a failed preload
        # never leaves a blank browser.
        if loaded_tabs:
            keep_ids = {t["id"] for t in loaded_tabs}
            for existing in _get_tabs():
                if existing["id"] not in keep_ids:
                    _close_tab(existing["id"])
        # Stagger each tab's first refresh across the interval (plus jitter) so they
        # don't all reload together once the cadence kicks in.
        if self._refresh_seconds > 0 and loaded_tabs:
            now = time.time()
            n = len(loaded_tabs)
            for i, tab in enumerate(loaded_tabs):
                spread = self._refresh_seconds * ((i + 1) / n)
                self._next_refresh[tab["id"]] = now + spread + random.uniform(0, self._refresh_seconds * 0.1)
        logger.info(
            "Playlist %s preloaded %d/%d tabs",
            self.playlist_id,
            len(self._tabs),
            len(self._items),
        )

    def _run(self) -> None:
        if not self._tabs:
            logger.warning("Playlist %s: no tabs preloaded, aborting", self.playlist_id)
            return
        logger.info("Playlist %s starting (%d tabs)", self.playlist_id, len(self._tabs))

        n = len(self._items)
        idx = min(self._start_idx, n - 1)
        with self._lock:
            self._current_idx = idx
            self._item_started_at = time.time()
        _activate_tab(self._tabs[idx]["id"])

        while True:
            item = self._items[idx]
            duration = item["duration_seconds"]
            logger.info(
                "Playlist %s [%d/%d] %s for %ds",
                self.playlist_id,
                idx + 1,
                n,
                item["url"],
                duration,
            )

            # Refresh the next tab now (while hidden) if it's due, so it's freshly
            # loaded by the time it rotates in.
            self._prerefresh_on_deck(idx)

            try:
                cmd, arg = self._cmd.get(timeout=duration)
            except queue.Empty:
                # Duration elapsed normally — advance to next item
                idx = (idx + 1) % n
                with self._lock:
                    self._current_idx = idx
                    self._item_started_at = time.time()
                next_url = self._items[idx].get("url", "?")
                if not _activate_tab(self._tabs[idx]["id"]):
                    logger.warning(
                        "Playlist %s auto-advance to [%d] %s: tab activation failed",
                        self._playlist_name,
                        idx + 1,
                        next_url,
                    )
                    _report_command(
                        f"playlist_advance: {self._playlist_name} [{idx + 1}] {next_url}",
                        False,
                        "Tab activation failed",
                    )
                continue

            if cmd == "stop":
                break
            elif cmd == "goto":
                target = max(0, min(arg, n - 1))
                item_url = self._items[target].get("url", "?")
                with self._lock:
                    self._current_idx = target
                    self._item_started_at = time.time()
                idx = target
                ok = _activate_tab(self._tabs[idx]["id"])
                logger.info(
                    "Playlist %s goto [%d] %s (%s)",
                    self._playlist_name,
                    idx + 1,
                    item_url,
                    "ok" if ok else "FAILED",
                )
                _report_command(
                    f"playlist_goto: {self._playlist_name} [{idx + 1}] {item_url}",
                    ok,
                    None if ok else "Tab activation failed",
                )

        logger.info("Playlist %s stopped", self.playlist_id)


class TabCycler:
    """Rotates focus through the node's currently-open browser tabs on a timer.

    Unlike PlaylistPlayer this never opens, preloads, or closes tabs — it only
    activates whatever tabs already exist, so newly opened or closed tabs are
    picked up automatically on the next tick. Tabs are visited in the operator's
    saved order (tab_order, a list of URLs); tabs whose URL isn't in that list
    are appended in CDP order. The rotation advances from whichever tab is
    currently on-screen, so a manual Focus simply shifts where the next hop lands.
    """

    def __init__(self, interval_seconds: int, tab_order: list[str] | None = None, on_rotate=None) -> None:
        self._interval = max(1, int(interval_seconds))
        self._tab_order = [u for u in (tab_order or []) if isinstance(u, str)]
        self._started_at = time.time()
        self._current_tab_id: str | None = None
        # Called after each rotation so the agent can push a heartbeat immediately,
        # keeping the dashboard's on-screen-tab highlight in sync with the rotation
        # instead of lagging until the next routine heartbeat.
        self._on_rotate = on_rotate
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=2)

    def _ordered_tabs(self, tabs: list[dict]) -> list[dict]:
        """Order live tabs by the saved URL order; unknown URLs keep CDP order at the end."""
        if not self._tab_order:
            return tabs
        rank = {url: i for i, url in enumerate(self._tab_order)}
        return sorted(tabs, key=lambda t: rank.get(t.get("url", ""), len(rank)))

    def _run(self) -> None:
        while not self._stop_event.wait(self._interval):
            tabs = self._ordered_tabs(_get_tabs())
            if not tabs:
                continue
            # Advance from the tab that's currently on-screen (falling back to the
            # one we last activated), so a manual Focus mid-cycle is respected.
            cur = next((i for i, t in enumerate(tabs) if t.get("active")), None)
            if cur is None:
                cur = next((i for i, t in enumerate(tabs) if t["id"] == self._current_tab_id), -1)
            nxt = tabs[(cur + 1) % len(tabs)]
            if _activate_tab(nxt["id"]):
                self._current_tab_id = nxt["id"]
                if self._on_rotate is not None:
                    try:
                        self._on_rotate()
                    except Exception as exc:
                        logger.debug("tab cycle on_rotate hook failed: %s", exc)

    def current_state(self) -> dict:
        return {
            "interval_seconds": self._interval,
            "current_tab_id": self._current_tab_id,
            "started_at": datetime.fromtimestamp(self._started_at, tz=timezone.utc).isoformat(),
        }
