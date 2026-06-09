"""command_logs

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-03
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "command_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kiosk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("command", sa.String(256), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("agent_success", sa.Boolean(), nullable=True),
        sa.Column("agent_message", sa.String(512), nullable=True),
        sa.Column("agent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["kiosk_id"], ["kiosks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_command_logs_kiosk_id", "command_logs", ["kiosk_id"])
    op.create_index("ix_command_logs_sent_at", "command_logs", ["sent_at"])


def downgrade() -> None:
    op.drop_table("command_logs")
