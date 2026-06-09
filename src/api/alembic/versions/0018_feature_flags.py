"""feature_flags

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-06
"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "feature_flags",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.execute(
        "INSERT INTO feature_flags (key, enabled) VALUES "
        "('browser_management', true), ('playlists', true), ('debug', true)"
    )


def downgrade():
    op.drop_table("feature_flags")
