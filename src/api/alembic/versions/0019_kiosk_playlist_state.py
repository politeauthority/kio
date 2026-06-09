"""kiosk_playlist_state

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-06
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "kiosks",
        sa.Column("playlist_state", postgresql.JSONB(), nullable=True),
    )


def downgrade():
    op.drop_column("kiosks", "playlist_state")
