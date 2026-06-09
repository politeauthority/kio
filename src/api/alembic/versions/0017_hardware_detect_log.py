"""hardware_detect_log

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-06
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hardware_detect_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kiosk_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("kiosks.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("capabilities", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("probes", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("hardware_info", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_hardware_detect_logs_detected_at", "hardware_detect_logs", ["detected_at"])


def downgrade() -> None:
    op.drop_table("hardware_detect_logs")
