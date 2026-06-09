"""playlist_refresh_interval

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-06
"""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "playlists",
        sa.Column("refresh_interval_seconds", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_column("playlists", "refresh_interval_seconds")
