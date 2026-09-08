"""Add no_show booking status + no_show_at timestamp.

Backs the "surrender a never-picked-up rental" feature: a booking still
`reserved`/`ready_for_pickup` once its return deadline passes can move to
the new terminal `no_show` status (via a user-triggered surrender endpoint,
or a lazy server-side check on next read), separate from a normal `cancelled`
booking so no-shows can be counted for the repeat-offender policy.

Revision ID: 20260908_0012
Revises: 20260901_0011
Create Date: 2026-09-08
"""

from alembic import op
import sqlalchemy as sa


revision = "20260908_0012"
down_revision = "20260901_0011"
branch_labels = None
depends_on = None


BOOKING_STATUS_CONSTRAINT = (
    "status IN ('reserved', 'ready_for_pickup', 'locker_opened', 'case_verified', "
    "'before_photos_complete', 'in_use', 'return_started', 'after_photos_complete', "
    "'return_locker_opened', 'return_video_complete', 'returned', 'cancelled', 'no_show')"
)

PRIOR_BOOKING_STATUS_CONSTRAINT = (
    "status IN ('reserved', 'ready_for_pickup', 'locker_opened', 'case_verified', "
    "'before_photos_complete', 'in_use', 'return_started', 'after_photos_complete', "
    "'return_locker_opened', 'return_video_complete', 'returned', 'cancelled')"
)


def upgrade() -> None:
    op.add_column("bookings", sa.Column("no_show_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("ALTER TABLE bookings DROP CONSTRAINT IF EXISTS ck_booking_status")
    op.create_check_constraint(
        "ck_booking_status",
        "bookings",
        BOOKING_STATUS_CONSTRAINT,
    )


def downgrade() -> None:
    op.execute("ALTER TABLE bookings DROP CONSTRAINT IF EXISTS ck_booking_status")
    op.create_check_constraint(
        "ck_booking_status",
        "bookings",
        PRIOR_BOOKING_STATUS_CONSTRAINT,
    )
    op.drop_column("bookings", "no_show_at")
