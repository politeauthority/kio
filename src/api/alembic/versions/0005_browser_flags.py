"""browser_flags

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-03
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

_DEFAULT = '["--force-dark-mode","--hide-scrollbars","--ignore-certificate-errors","--disable-session-crashed-bubble","--no-first-run"]'


def upgrade() -> None:
    op.add_column(
        "kiosks",
        sa.Column("browser_flags", sa.JSON(), nullable=False, server_default=_DEFAULT),
    )


def downgrade() -> None:
    op.drop_column("kiosks", "browser_flags")
