"""Fix admin profile role constraint.

Revision ID: 20260612_0004
Revises: 20260612_0003
Create Date: 2026-06-12
"""

from alembic import op


revision = "20260612_0004"
down_revision = "20260612_0003"
branch_labels = None
depends_on = None


ADMIN_ROLE_CONSTRAINT = (
    "role IN ('owner', 'master_developer', 'manager', 'developer', 'admin')"
)


def upgrade() -> None:
    op.execute("ALTER TABLE admin_profiles DROP CONSTRAINT IF EXISTS ck_admin_profiles_role")
    op.create_check_constraint(
        "ck_admin_profiles_role",
        "admin_profiles",
        ADMIN_ROLE_CONSTRAINT,
    )


def downgrade() -> None:
    op.execute("ALTER TABLE admin_profiles DROP CONSTRAINT IF EXISTS ck_admin_profiles_role")
    op.create_check_constraint(
        "ck_admin_profiles_role",
        "admin_profiles",
        ADMIN_ROLE_CONSTRAINT,
    )
