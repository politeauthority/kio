"""kiosk_tab_cycle_state

Revision ID: 0031
Revises: 0030
Create Date: 2026-06-10
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "kiosks",
        sa.Column("tab_cycle_state", postgresql.JSONB(), nullable=True),
    )


def downgrade():
    op.drop_column("kiosks", "tab_cycle_state")
