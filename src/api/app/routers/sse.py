import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from starlette.requests import Request

from app.mqtt import subscribe, unsubscribe

router = APIRouter()


@router.get("/kiosks/{kiosk_id}/sse")
async def kiosk_sse(kiosk_id: str, request: Request):
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
