"""agent_update_log

Revision ID: 0032
Revises: 0031
Create Date: 2026-06-11

Note: this table backed an earlier "agent update log" feature that was rolled back
at the application layer, but the migration had already been applied to prod (the
alembic_version was left at 0032). This file is retained so `alembic upgrade head`
can resolve revision 0032; on an already-migrated DB it is a no-op, and on a fresh
DB it creates the table.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_update_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kiosk_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("kiosks.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("reported_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ref", sa.String(length=128), nullable=True),
        sa.Column("from_version", sa.String(length=64), nullable=True),
        sa.Column("to_version", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="unknown"),
        sa.Column("command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("log", sa.Text(), nullable=False, server_default=""),
    )
    op.create_index("ix_agent_update_logs_reported_at", "agent_update_logs", ["reported_at"])


def downgrade() -> None:
    op.drop_table("agent_update_logs")
