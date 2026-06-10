"""drop graduated browser_management feature flag

browser_management graduated to always-on — the Browsers section is now a core
feature, no longer gated. Remove the orphaned row seeded by 0018 so it stops
lingering in the feature_flags table. The application code already dropped it
from KNOWN_FLAGS, so the row was inert; this is cleanup only.

Revision ID: 0030
Revises: 0029
Create Date: 2026-06-09
"""

from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("DELETE FROM feature_flags WHERE key = 'browser_management'")


def downgrade():
    # Re-seed the flag as enabled (its historical default) on rollback.
    op.execute(
        "INSERT INTO feature_flags (key, enabled) VALUES ('browser_management', true) "
        "ON CONFLICT (key) DO NOTHING"
    )
