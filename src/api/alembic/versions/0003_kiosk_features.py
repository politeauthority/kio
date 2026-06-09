"""kiosk_features

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-03
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "kiosks",
        sa.Column("features", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("kiosks", "features")
