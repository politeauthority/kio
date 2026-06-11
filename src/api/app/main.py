import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.auth import refresh_jwks, require_dashboard_auth
from app.config import settings
from app.mqtt import start_mqtt, stop_mqtt
from app.routers import agent, agent_settings, auth, certificates, event_logs, feature_flags, kiosks, managed_api_keys, node_settings, playlists, saved_urls, sse, tokens
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
                await mark_offline_kiosks(
                    session,
                    settings_["node_offline_threshold_seconds"],
                    heartbeat_interval=settings_["heartbeat_interval_seconds"],
                    heartbeat_jitter=settings_["heartbeat_jitter_seconds"],
                )
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


app = FastAPI(
    title="kio",
    lifespan=lifespan,
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)

_FAVICON_PATH = Path(__file__).parent / "static" / "favicon.svg"


@app.get("/favicon.svg", include_in_schema=False)
@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    return FileResponse(_FAVICON_PATH, media_type="image/svg+xml")

# CORS is only exercised when the UI is served from a different origin than the
# API. In every standard deployment the UI reaches the API same-origin via a
# proxy (Vite '/api' in dev, nginx '/api/' in prod/Docker), so CORS never fires.
# It therefore stays locked down: no credentials (auth is a Bearer header, not a
# cookie), and an explicit method/header allow-list. Cross-origin setups must add
# their UI origin to CORS_ORIGINS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
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
app.include_router(sse.router)  # ticket-issue route is authed; stream is ticket-gated
app.include_router(playlists.router, dependencies=_dashboard_auth)
app.include_router(feature_flags.router, dependencies=_dashboard_auth)
app.include_router(agent_settings.router, dependencies=_dashboard_auth)
app.include_router(event_logs.router, dependencies=_dashboard_auth)
app.include_router(saved_urls.router, dependencies=_dashboard_auth)
app.include_router(managed_api_keys.router, dependencies=_dashboard_auth)
app.include_router(node_settings.router, dependencies=_dashboard_auth)
app.include_router(certificates.router, dependencies=_dashboard_auth)


@app.get("/_migrations", dependencies=_dashboard_auth)
async def migrations() -> dict:
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import text

    from app.database import async_session_factory

    head_revision = None
    current_revision = None
    error = None

    try:
        alembic_ini = Path(__file__).parent.parent / "alembic.ini"
        cfg = Config(str(alembic_ini))
        script = ScriptDirectory.from_config(cfg)
        head_revision = script.get_current_head()
    except Exception as exc:
        error = f"Could not read head revision: {exc}"
        logger.error("Migrations head error: %s", exc)

    try:
        async with async_session_factory() as session:
            row = (await session.execute(text("SELECT version_num FROM alembic_version"))).fetchone()
            current_revision = row[0] if row else None
    except Exception as exc:
        error = f"Could not read current revision: {exc}"
        logger.error("Migrations current error: %s", exc)

    return {
        "current_revision": current_revision,
        "head_revision": head_revision,
        "up_to_date": current_revision is not None and current_revision == head_revision,
        "error": error,
    }


@app.get("/_version")
async def version() -> dict:
    from app.version import agent_expected_version, server_version

    # agent_version is the base version the server expects nodes to run, so the
    # dashboard can flag a node whose reported version is older.
    return {"version": server_version(), "agent_version": agent_expected_version()}


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
