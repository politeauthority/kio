"""agent_version

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-04
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("kiosks", sa.Column("agent_version", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("kiosks", "agent_version")
