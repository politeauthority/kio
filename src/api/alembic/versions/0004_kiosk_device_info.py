"""kiosk_device_info

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-03
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("kiosks", sa.Column("device_type", sa.String(128), nullable=True))
    op.add_column("kiosks", sa.Column("ip_address", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("kiosks", "ip_address")
    op.drop_column("kiosks", "device_type")
