"""Resolve a kiosk's current URL to the saved URL it was registered as.

Saved URLs (Settings → URLs) give a page a name. Anything that displays a
kiosk's current page — the dashboard, Home Assistant — would rather show
"Grafana — Office" than the URL itself, so the API resolves the match once here
and every consumer reads `current_url_name` off the kiosk record instead of
re-implementing the comparison.
"""

from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.saved_url import SavedUrl


def normalize_url(url: str | None) -> str:
    """Canonical form for comparing URLs: scheme and host lower-cased, default
    ports dropped, trailing slash on the path removed, fragment ignored. Query
    strings are kept — `?panelId=3` is a different page. Anything unparseable
    compares as its stripped self."""
    if not url:
        return ""
    raw = url.strip()
    try:
        parts = urlsplit(raw)
    except ValueError:
        return raw.rstrip("/")
    if not parts.scheme or not parts.netloc:
        return raw.rstrip("/")
    host = (parts.hostname or "").lower()
    port = parts.port
    if port and not (
        (parts.scheme == "http" and port == 80) or (parts.scheme == "https" and port == 443)
    ):
        host = f"{host}:{port}"
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), host, path, parts.query, ""))


def match_saved_url(url: str | None, saved: list[SavedUrl]) -> SavedUrl | None:
    key = normalize_url(url)
    if not key:
        return None
    for s in saved:
        if normalize_url(s.url) == key:
            return s
    return None


async def annotate_url_names(session: AsyncSession, kiosks) -> None:
    """Set `current_url_name` / `current_saved_url_id` on each kiosk in place.

    One query for the saved-URL table, then an in-memory match per kiosk. The
    attributes are plain Python attributes on the ORM instance (not columns);
    KioskRead picks them up via from_attributes.
    """
    kiosks = list(kiosks)
    for k in kiosks:
        k.current_url_name = None
        k.current_saved_url_id = None
    if not any(k.current_url for k in kiosks):
        return
    result = await session.execute(select(SavedUrl))
    saved = list(result.scalars().all())
    if not saved:
        return
    for k in kiosks:
        hit = match_saved_url(k.current_url, saved)
        if hit is not None:
            k.current_url_name = hit.name
            k.current_saved_url_id = hit.id
