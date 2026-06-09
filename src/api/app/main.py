import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.auth import refresh_jwks, require_dashboard_auth
from app.config import settings
from app.mqtt import start_mqtt, stop_mqtt
from app.routers import agent, agent_settings, auth, event_logs, feature_flags, kiosks, managed_api_keys, node_settings, playlists, saved_urls, sse, tokens
from app.services.kiosk_service import mark_offline_kiosks, update_kiosk_from_heartbeat

logging.basicConfig(level=settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("kio.main")


async def _offline_sweeper() -> None:
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import delete

    from app.database import async_session_factory
    from app.models.command_log import CommandLog
    from app.services.settings_service import get_global_settings

    ticks = 0
    while True:
        await asyncio.sleep(60)
        ticks += 1
        try:
            async with async_session_factory() as session:
                # Settings are read every sweep so the health-check timeout (and
                # purge window) can be tuned live from Settings → Agents.
                settings_ = await get_global_settings(session)
                await mark_offline_kiosks(session, settings_["node_offline_threshold_seconds"])
                # Purge old event-log entries (runs hourly).
                if ticks % 60 == 0:
                    cutoff = datetime.now(timezone.utc) - timedelta(days=settings_["event_log_purge_days"])
                    result = await session.execute(delete(CommandLog).where(CommandLog.sent_at < cutoff))
                    await session.commit()
                    logger.info("Purged %d event-log entries older than %d days", result.rowcount, settings_["event_log_purge_days"])
        except Exception as exc:
            logger.error("Offline sweeper error: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await refresh_jwks()
    loop = asyncio.get_event_loop()
    start_mqtt(loop, update_kiosk_from_heartbeat)
    sweeper = asyncio.create_task(_offline_sweeper())
    yield
    sweeper.cancel()
    stop_mqtt()


app = FastAPI(title="kio", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - start) * 1000
    log = logger.debug if request.url.path == "/_health" else logger.info
    log("%s %s %d %.1fms", request.method, request.url.path, response.status_code, ms)
    return response


_dashboard_auth = [Depends(require_dashboard_auth)]

app.include_router(kiosks.router, dependencies=_dashboard_auth)
app.include_router(tokens.router, dependencies=_dashboard_auth)
app.include_router(auth.router)  # public — issues dev tokens
app.include_router(agent.router)  # authenticated separately via NodeToken
app.include_router(sse.router, dependencies=_dashboard_auth)
app.include_router(playlists.router, dependencies=_dashboard_auth)
app.include_router(feature_flags.router, dependencies=_dashboard_auth)
app.include_router(agent_settings.router, dependencies=_dashboard_auth)
app.include_router(event_logs.router, dependencies=_dashboard_auth)
app.include_router(saved_urls.router, dependencies=_dashboard_auth)
app.include_router(managed_api_keys.router, dependencies=_dashboard_auth)
app.include_router(node_settings.router, dependencies=_dashboard_auth)


@app.get("/_version")
async def version() -> dict:
    import os

    return {"version": os.environ.get("KIO_VERSION", "dev")}


@app.get("/_health")
async def health() -> dict:
    from sqlalchemy import text

    from app.database import async_session_factory
    from app.mqtt import _client as mqtt_client

    checks: dict[str, str] = {}

    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as exc:
        logger.error("Health check db failed: %s", exc)
        checks["db"] = "error"

    checks["mqtt"] = "ok" if mqtt_client and mqtt_client.is_connected() else "error"

    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": status, "checks": checks}
