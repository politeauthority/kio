"""last_boot_id

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-04
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("kiosks", sa.Column("last_boot_id", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("kiosks", "last_boot_id")
