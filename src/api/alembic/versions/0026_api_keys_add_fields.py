"""api_keys: add key_prefix and is_active columns

Revision ID: 0026
Revises: 0025
Create Date: 2026-06-06
"""
import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("api_keys", sa.Column("key_prefix", sa.String(16), nullable=False, server_default=""))
    op.add_column("api_keys", sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"))


def downgrade() -> None:
    op.drop_column("api_keys", "is_active")
    op.drop_column("api_keys", "key_prefix")
