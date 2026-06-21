"""Chrome DevTools Protocol (CDP) helpers.

Thin wrappers around Chromium's debugging endpoint on ``CDP_BASE``: listing tabs,
opening/closing/activating/reloading them, navigating, and running one-shot CDP
methods over a WebSocket. All functions are best-effort and log rather than raise
when Chromium is unreachable, except :func:`navigate`, which raises on a
disallowed URL scheme (a security boundary).
"""

import json

import requests
import websocket

from kio_agent.constants import _ALLOWED_URL_SCHEMES, _FADE_IN_SOURCE, CDP_BASE, logger


def _get_tab() -> dict | None:
    try:
        resp = requests.get(f"{CDP_BASE}/json", timeout=2)
        tabs = [t for t in resp.json() if t.get("type") == "page"]
        return tabs[0] if tabs else None
    except Exception as exc:
        logger.warning("CDP unreachable: %s", exc)
        return None


def _wait_for_chromium(timeout: float = 60.0) -> bool:
    """Block until Chromium is ready to be controlled over CDP, or until timeout.

    Checks the browser-level WebSocket endpoint (/json/version), not just /json:
    the tab-list endpoint answers a moment before the browser WS — which is what
    Target.createTarget (opening tabs) actually needs — is ready. Waiting on the
    weaker signal let playlist preloads run too early and fail with 'no browser WS
    url available', collapsing the playlist to a single tab. Used at boot resume
    and before every playlist preload.
    """
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        if _browser_ws_url():
            return True
        time.sleep(2)
    return False


def _tab_info(tab: dict) -> dict:
    """Per-tab runtime info read from the page itself: seconds since it last loaded
    (via its performance clock, so it reflects real reloads) and whether it's the
    visible/foreground tab. Falls back to unknown values if it can't be read."""
    try:
        r = _cdp_call(
            tab,
            "Runtime.evaluate",
            {
                # responseStatus is the HTTP status of the main-document navigation
                # (Chromium >=109); 0/undefined for about:blank, cached, or failed loads,
                # which we collapse to null so the dashboard can omit the badge.
                "expression": "({age: Math.round((Date.now() - performance.timeOrigin) / 1000),"
                " active: document.visibilityState === 'visible',"
                " status: ((performance.getEntriesByType('navigation')[0] || {}).responseStatus) || null})",
                "returnByValue": True,
            },
        )
        val = (((r or {}).get("result") or {}).get("result") or {}).get("value") or {}
        age = val.get("age")
        status = val.get("status")
        return {
            "age_seconds": int(age) if age is not None else None,
            "active": bool(val.get("active")),
            "http_status": int(status) if status else None,
        }
    except Exception:
        return {"age_seconds": None, "active": False, "http_status": None}


def _normalize_url(url: str) -> str:
    """Canonical form for deciding two tabs show the same page: drop the URL
    fragment (same document) and a single trailing slash. Query strings are kept
    — they usually denote a genuinely different page."""
    u = (url or "").split("#", 1)[0]
    return u[:-1] if u.endswith("/") else u


def _get_tabs() -> list[dict]:
    try:
        resp = requests.get(f"{CDP_BASE}/json", timeout=2)
        out = []
        for t in resp.json():
            if t.get("type") != "page":
                continue
            info = _tab_info(t)
            out.append(
                {
                    "id": t["id"],
                    "url": t.get("url", ""),
                    "title": t.get("title", ""),
                    "age_seconds": info["age_seconds"],
                    "active": info["active"],
                }
            )
        return out
    except Exception as exc:
        logger.warning("CDP tabs unreachable: %s", exc)
        return []


def _cdp_call(tab: dict, method: str, params: dict | None = None) -> dict | None:
    ws_url = tab.get("webSocketDebuggerUrl")
    if not ws_url:
        return None
    payload = json.dumps({"id": 1, "method": method, "params": params or {}})
    try:
        ws = websocket.create_connection(ws_url, timeout=5)
        ws.send(payload)
        result = json.loads(ws.recv())
        ws.close()
        return result
    except Exception as exc:
        logger.error("CDP %s failed: %s", method, exc)
        return None


def is_safe_url(url: str) -> bool:
    return isinstance(url, str) and url.strip().lower().startswith(_ALLOWED_URL_SCHEMES)


def navigate(url: str) -> None:
    if not is_safe_url(url):
        logger.warning("navigate: rejected disallowed URL scheme: %r", url)
        raise ValueError(f"disallowed URL scheme: {url!r}")
    tab = _get_tab()
    if tab:
        _cdp_call(tab, "Page.navigate", {"url": url})
        logger.info("Navigated to %s", url)
    else:
        logger.warning("navigate: no CDP tab available")


def reload_page() -> None:
    tab = _get_tab()
    if tab:
        _cdp_call(tab, "Page.reload")
        logger.info("Reloaded page")
    else:
        logger.warning("reload: no CDP tab available")


def get_current_url() -> str | None:
    tab = _get_tab()
    return tab.get("url") if tab else None


def _browser_ws_url() -> str | None:
    """Return the browser-level CDP WebSocket URL (for Target.* methods)."""
    try:
        resp = requests.get(f"{CDP_BASE}/json/version", timeout=2)
        return resp.json().get("webSocketDebuggerUrl")
    except Exception as exc:
        logger.warning("Failed to read browser WS url: %s", exc)
        return None


def _open_tab(url: str) -> dict | None:
    """Open a new background tab and return the full CDP tab dict, or None on failure.

    Uses Target.createTarget over the browser-level WebSocket. The HTTP
    /json/new endpoint was restricted in modern Chromium (returns an empty body
    over GET), so the WebSocket path is the version-stable way to create tabs.
    """
    ws_url = _browser_ws_url()
    if not ws_url:
        logger.warning("_open_tab: no browser WS url available for %s", url)
        return None

    # Create the target in the background so the active tab keeps showing.
    payload = json.dumps(
        {
            "id": 1,
            "method": "Target.createTarget",
            "params": {"url": url, "background": True},
        }
    )
    try:
        ws = websocket.create_connection(ws_url, timeout=5)
        ws.send(payload)
        result = json.loads(ws.recv())
        ws.close()
    except Exception as exc:
        logger.warning("Failed to open preload tab for %s: %s", url, exc)
        return None

    target_id = (result.get("result") or {}).get("targetId")
    if not target_id:
        logger.warning("_open_tab: createTarget returned no targetId (%r) for %s", result, url)
        return None

    # Resolve the full tab dict (with the page-level webSocketDebuggerUrl) from
    # the HTTP list, which GET still serves reliably.
    try:
        for t in requests.get(f"{CDP_BASE}/json", timeout=2).json():
            if t.get("id") == target_id:
                logger.info("Opened preload tab %s for %s", target_id, url)
                return t
    except Exception as exc:
        logger.warning("_open_tab: failed to resolve tab %s: %s", target_id, exc)
        return None

    logger.warning("_open_tab: tab %s not found in /json list for %s", target_id, url)
    return None


def _install_fade_script(tab: dict) -> None:
    """Install the fade-in script in a tab (best-effort, non-blocking)."""
    # Persistent: runs before page JS on every future navigation within this tab
    _cdp_call(tab, "Page.addScriptToEvaluateOnNewDocument", {"source": _FADE_IN_SOURCE})
    # Current document: handles the race where the page loads before the above lands
    _cdp_call(tab, "Runtime.evaluate", {"expression": _FADE_IN_SOURCE})


def _activate_tab(tab_id: str) -> bool:
    try:
        requests.get(f"{CDP_BASE}/json/activate/{tab_id}", timeout=3)
        return True
    except Exception as exc:
        logger.warning("Failed to activate tab %s: %s", tab_id, exc)
        return False


def _close_tab(tab_id: str) -> None:
    try:
        requests.get(f"{CDP_BASE}/json/close/{tab_id}", timeout=3)
    except Exception as exc:
        logger.debug("Failed to close tab %s: %s", tab_id, exc)


def _reload_tab(tab: dict) -> bool:
    """Reload a preloaded tab's page in place (keeps playlist content fresh)."""
    if _cdp_call(tab, "Page.reload", {}) is not None:
        return True
    logger.debug("Failed to reload tab %s", tab.get("id"))
    return False
