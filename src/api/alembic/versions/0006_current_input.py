"""current_input

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-03
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("kiosks", sa.Column("current_input", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("kiosks", "current_input")
