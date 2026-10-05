"""One-time: require every existing admin to change their password.

Before this, the forced first-login password change was tracked partly on
the device, so the server could not tell which current admins had already
replaced a temporary password. Owner decision (2026-10-05): flag every
existing admin once so the server becomes the single source of truth.
Each admin changes it once, on whichever client they use first
(POST /api/users/me/change-password clears the flag), and is never asked
again on any other client.

New staff accounts are already created with must_change_password = true by
admin_service; the first-owner setup flow still creates it as false, since
that owner chose their own password. Neither is changed here.

Revision ID: 20261005_0015
Revises: 20260915_0014
Create Date: 2026-10-05
"""

from alembic import op


revision = "20261005_0015"
down_revision = "20260915_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE admin_profiles SET must_change_password = true")


def downgrade() -> None:
    # Data-only migration; there is no meaningful prior state to restore
    # (we cannot know who had already changed their password).
    pass
