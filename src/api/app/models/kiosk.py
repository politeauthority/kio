import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.node_meta import NodeMeta


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Kiosk(Base):
    __tablename__ = "kiosks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    hostname: Mapped[str] = mapped_column(String(253), nullable=False)
    current_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    features: Mapped[list] = mapped_column(JSON, nullable=False, server_default="[]")
    device_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_input: Mapped[str | None] = mapped_column(String(16), nullable=True)
    display_on: Mapped[bool | None] = mapped_column(nullable=True)
    agent_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_boot_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # System uptime the node last reported (metadata heartbeat) and when it arrived,
    # so the dashboard can extrapolate the live uptime while the node stays online.
    uptime_seconds: Mapped[int | None] = mapped_column(nullable=True)
    uptime_reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reporting_api_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    playlist_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("playlists.id", ondelete="SET NULL"), nullable=True
    )
    browser_flags: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        server_default='["--force-dark-mode","--hide-scrollbars","--ignore-certificate-errors","--disable-session-crashed-bubble","--no-first-run"]',
    )
    browser_tabs: Mapped[list] = mapped_column(JSON, nullable=False, server_default="[]")
    playlist_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tab_cycle_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=_now)

    meta_rows: Mapped[list["NodeMeta"]] = relationship("NodeMeta", cascade="all, delete-orphan", lazy="selectin")

    @property
    def meta(self) -> dict:
        return {row.key: row.value for row in self.meta_rows}
