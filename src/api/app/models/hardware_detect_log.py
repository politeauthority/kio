import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class HardwareDetectLog(Base):
    __tablename__ = "hardware_detect_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kiosk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("kiosks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    capabilities: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    probes: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    hardware_info: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
