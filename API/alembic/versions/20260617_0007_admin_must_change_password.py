"""Add must_change_password to admin_profiles.

Revision ID: 20260617_0007
Revises: 20260617_0006
Create Date: 2026-06-17
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260617_0007"
down_revision = "20260617_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing admins have already set their own passwords, so default to False.
    op.add_column(
        "admin_profiles",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("admin_profiles", "must_change_password")
