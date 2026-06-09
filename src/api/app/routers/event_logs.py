import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.command_log import CommandLog
from app.models.kiosk import Kiosk
from app.routers.kiosks import COMMAND_RESPONSE_TIMEOUT_SECONDS, _command_status

router = APIRouter(prefix="/event-logs", tags=["event-logs"])

# Derived statuses a row can resolve to — see _command_status in the kiosks router.
EVENT_STATUSES = ("ok", "failed", "pending", "no_response")


class EventLogRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    kiosk_id: uuid.UUID
    kiosk_name: str
    command: str
    subject: str | None
    source: str
    sent_at: datetime
    agent_success: bool | None
    agent_message: str | None
    agent_at: datetime | None
    # Derived display status: "ok" | "failed" | "pending" | "no_response"
    status: str


def _apply_status_filter(stmt, status: str, now: datetime):
    """Translate a derived status into the equivalent column predicate. Mirrors
    _command_status so the filter and the displayed value never disagree."""
    cutoff = now - timedelta(seconds=COMMAND_RESPONSE_TIMEOUT_SECONDS)
    if status == "ok":
        return stmt.where(CommandLog.agent_success.is_(True))
    if status == "failed":
        return stmt.where(CommandLog.agent_success.is_(False))
    if status == "pending":
        return stmt.where(CommandLog.agent_success.is_(None), CommandLog.sent_at > cutoff)
    # no_response
    return stmt.where(CommandLog.agent_success.is_(None), CommandLog.sent_at <= cutoff)


@router.get("", response_model=list[EventLogRead])
async def search_event_logs(
    response: Response,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    kiosk_id: uuid.UUID | None = Query(default=None),
    command: str = Query(default="", description="Exact event type (command) match"),
    status: str = Query(default="", description="One of: ok | failed | pending | no_response"),
    search: str = Query(default="", description="Free-text match on command, subject, or agent message"),
    session: AsyncSession = Depends(get_session),
):
    """Search the event log across all kiosks and the system."""
    now = datetime.now(timezone.utc)

    base = select(CommandLog, Kiosk.name).join(Kiosk, CommandLog.kiosk_id == Kiosk.id)
    if kiosk_id is not None:
        base = base.where(CommandLog.kiosk_id == kiosk_id)
    if command:
        base = base.where(CommandLog.command == command)
    if status in EVENT_STATUSES:
        base = _apply_status_filter(base, status, now)
    if search:
        like = f"%{search}%"
        base = base.where(
            CommandLog.command.ilike(like)
            | CommandLog.subject.ilike(like)
            | CommandLog.agent_message.ilike(like)
        )

    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        await session.execute(base.order_by(CommandLog.sent_at.desc()).limit(limit).offset(offset))
    ).all()

    result = [
        EventLogRead(
            id=log.id,
            kiosk_id=log.kiosk_id,
            kiosk_name=kiosk_name,
            command=log.command,
            subject=log.subject,
            source=log.source,
            sent_at=log.sent_at,
            agent_success=log.agent_success,
            agent_message=log.agent_message,
            agent_at=log.agent_at,
            status=_command_status(log, now),
        )
        for log, kiosk_name in rows
    ]

    response.headers["X-Total-Count"] = str(total)
    return result


@router.get("/commands", response_model=list[str])
async def list_event_commands(session: AsyncSession = Depends(get_session)):
    """Distinct command names, for populating the event-type filter dropdown."""
    rows = await session.execute(select(CommandLog.command).distinct().order_by(CommandLog.command))
    return [r for r in rows.scalars().all()]
