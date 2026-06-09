"""display_on

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-03
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("kiosks", sa.Column("display_on", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("kiosks", "display_on")
