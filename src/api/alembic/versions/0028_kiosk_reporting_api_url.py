"""kiosks: add reporting_api_url column

Revision ID: 0028
Revises: 0027
Create Date: 2026-06-08
"""
import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("kiosks", sa.Column("reporting_api_url", sa.String(512), nullable=True))


def downgrade() -> None:
    op.drop_column("kiosks", "reporting_api_url")
