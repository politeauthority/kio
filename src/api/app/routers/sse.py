import asyncio
import json
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from starlette.requests import Request

from app.auth import require_dashboard_auth
from app.mqtt import subscribe, unsubscribe

router = APIRouter()

# Short-lived, single-use tickets for SSE. The browser EventSource API can't set
# an Authorization header, so the stream is authorized with a ticket in the query
# string instead of the long-lived bearer token (which would otherwise leak into
# access logs / proxy logs). Tickets are minted by an authenticated request,
# expire within seconds, and are consumed on first use.
_TICKET_TTL_SECONDS = 30.0
_tickets: dict[str, tuple[str, float]] = {}  # ticket -> (kiosk_id, expires_at)


def _prune_tickets() -> None:
    now = time.monotonic()
    for tk, (_, expires_at) in list(_tickets.items()):
        if expires_at < now:
            _tickets.pop(tk, None)


def _issue_ticket(kiosk_id: str) -> str:
    _prune_tickets()
    ticket = secrets.token_urlsafe(32)
    _tickets[ticket] = (kiosk_id, time.monotonic() + _TICKET_TTL_SECONDS)
    return ticket


def _consume_ticket(ticket: str, kiosk_id: str) -> bool:
    entry = _tickets.pop(ticket, None)
    if entry is None:
        return False
    tk_kiosk_id, expires_at = entry
    return tk_kiosk_id == kiosk_id and time.monotonic() < expires_at


@router.post("/kiosks/{kiosk_id}/sse-ticket", dependencies=[Depends(require_dashboard_auth)])
async def sse_ticket(kiosk_id: str) -> dict:
    return {"ticket": _issue_ticket(kiosk_id)}


@router.get("/kiosks/{kiosk_id}/sse")
async def kiosk_sse(kiosk_id: str, request: Request, ticket: str = Query(default="")):
    if not _consume_ticket(ticket, kiosk_id):
        raise HTTPException(status_code=401, detail="Invalid or expired SSE ticket")

    queue: asyncio.Queue = asyncio.Queue()
    subscribe(kiosk_id, queue)

    async def event_stream():
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"event: status\ndata: {json.dumps(payload)}\n\n"
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        break
                    yield ": keepalive\n\n"
        finally:
            unsubscribe(kiosk_id, queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
