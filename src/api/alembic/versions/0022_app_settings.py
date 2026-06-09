"""app_settings

Global key/value store for non-boolean settings (agent heartbeat/checkin tuning,
event-log purge window). Seeded with the agent setting defaults.

Revision ID: 0022
Revises: 0021
Create Date: 2026-06-06
"""

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=True),
    )
    op.execute(
        "INSERT INTO app_settings (key, value) VALUES "
        "('heartbeat_interval_seconds', '30'), "
        "('heartbeat_jitter_seconds', '0'), "
        "('metadata_interval_seconds', '3600'), "
        "('settings_checkin_seconds', '300'), "
        "('event_log_purge_days', '7')"
    )


def downgrade():
    op.drop_table("app_settings")
