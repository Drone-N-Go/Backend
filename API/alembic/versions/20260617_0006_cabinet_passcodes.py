"""Add locker_hardware_id to locker_locations and current_passcode to locker_units.

Revision ID: 20260617_0006
Revises: 20260612_0005
Create Date: 2026-06-17
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260617_0006"
down_revision = "20260612_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add the hardware identifier for the physical locker unit (e.g. "A1", "UNIT-01").
    # Nullable so existing rows are unaffected; new locations will always populate it.
    op.add_column(
        "locker_locations",
        sa.Column("locker_hardware_id", sa.String(255), nullable=True),
    )

    # Add the active passcode for each cabinet.
    # Set by the webhook on PackageDeposited, cleared on PackagePickedUp.
    op.add_column(
        "locker_units",
        sa.Column("current_passcode", sa.String(50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("locker_units", "current_passcode")
    op.drop_column("locker_locations", "locker_hardware_id")
