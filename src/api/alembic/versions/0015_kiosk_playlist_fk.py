"""kiosk_playlist_fk

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-04
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "kiosks",
        sa.Column("playlist_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_kiosks_playlist_id",
        "kiosks",
        "playlists",
        ["playlist_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_kiosks_playlist_id", "kiosks", type_="foreignkey")
    op.drop_column("kiosks", "playlist_id")
