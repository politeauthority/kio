import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CommandLog(Base):
    __tablename__ = "command_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kiosk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("kiosks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    command: Mapped[str] = mapped_column(String(256), nullable=False)
    # The thing the command acted on — e.g. a URL for "navigate", a tab id for
    # "activate_tab". Kept separate from `command` so the event-type filter isn't
    # polluted with per-event ids/URLs.
    subject: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)  # "dashboard" | "agent"
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    agent_success: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    agent_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    agent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
