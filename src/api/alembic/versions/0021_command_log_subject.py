"""command_log_subject

Splits the event subject (URL, tab id, playlist name) out of the command
string into its own column so the event-type filter stays clean.

Revision ID: 0021
Revises: 0020
Create Date: 2026-06-06
"""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("command_logs", sa.Column("subject", sa.String(length=512), nullable=True))


def downgrade():
    op.drop_column("command_logs", "subject")
