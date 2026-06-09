"""browser_tabs

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-05
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "kiosks",
        sa.Column(
            "browser_tabs",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("kiosks", "browser_tabs")
