"""node_offline_threshold setting

Seed the node health-check timeout into app_settings so it can be tuned live
from Settings → Agents (previously a static env/config value).

Revision ID: 0023
Revises: 0022
Create Date: 2026-06-06
"""

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "INSERT INTO app_settings (key, value) VALUES ('node_offline_threshold_seconds', '90') "
        "ON CONFLICT (key) DO NOTHING"
    )


def downgrade():
    op.execute("DELETE FROM app_settings WHERE key = 'node_offline_threshold_seconds'")
