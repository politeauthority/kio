"""node_meta

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-04
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "node_meta",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kiosk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["kiosk_id"], ["kiosks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kiosk_id", "key", name="uq_node_meta_kiosk_key"),
    )
    op.create_index("ix_node_meta_kiosk_id", "node_meta", ["kiosk_id"])


def downgrade() -> None:
    op.drop_table("node_meta")
