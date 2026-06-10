"""kiosks: add uptime_seconds + uptime_reported_at columns

Revision ID: 0029
Revises: 0028
Create Date: 2026-06-09
"""
import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("kiosks", sa.Column("uptime_seconds", sa.Integer(), nullable=True))
    op.add_column("kiosks", sa.Column("uptime_reported_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("kiosks", "uptime_reported_at")
    op.drop_column("kiosks", "uptime_seconds")
