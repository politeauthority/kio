"""data retention settings

Seed the hardware-detect-log retention and the node update-log size cap into
app_settings so they can be tuned from Settings → Data retention.

Revision ID: 0033
Revises: 0032
Create Date: 2026-08-29
"""

from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "INSERT INTO app_settings (key, value) VALUES "
        "('hardware_log_purge_days', '30'), ('node_update_log_max_kb', '256') "
        "ON CONFLICT (key) DO NOTHING"
    )


def downgrade():
    op.execute("DELETE FROM app_settings WHERE key IN ('hardware_log_purge_days', 'node_update_log_max_kb')")
