"""Stripe payments: pending_payment booking status, payment columns,
users.stripe_customer_id, and a stripe_events table for webhook dedupe.

Existing bookings are untouched (payment columns stay NULL = no payment
recorded). Nothing changes behaviour until PAYMENTS_ENABLED is set.

Revision ID: 20261005_0016
Revises: 20261005_0015
Create Date: 2026-10-05
"""

from alembic import op
import sqlalchemy as sa


revision = "20261005_0016"
down_revision = "20261005_0015"
branch_labels = None
depends_on = None


BOOKING_STATUS_CONSTRAINT = (
    "status IN ('pending_payment', 'reserved', 'ready_for_pickup', 'locker_opened', "
    "'case_verified', 'before_photos_complete', 'in_use', 'return_started', "
    "'after_photos_complete', 'return_locker_opened', 'return_video_complete', "
    "'returned', 'cancelled', 'no_show')"
)

PRIOR_BOOKING_STATUS_CONSTRAINT = (
    "status IN ('reserved', 'ready_for_pickup', 'locker_opened', 'case_verified', "
    "'before_photos_complete', 'in_use', 'return_started', 'after_photos_complete', "
    "'return_locker_opened', 'return_video_complete', 'returned', 'cancelled', 'no_show')"
)


def upgrade() -> None:
    op.add_column("bookings", sa.Column("payment_status", sa.String(30), nullable=True))
    op.add_column("bookings", sa.Column("stripe_payment_intent_id", sa.String(255), nullable=True))
    op.add_column("bookings", sa.Column("amount_paid_cents", sa.Integer(), nullable=True))
    op.add_column("bookings", sa.Column("stripe_fee_cents", sa.Integer(), nullable=True))
    op.add_column("bookings", sa.Column("refunded_amount_cents", sa.Integer(), nullable=True))
    op.add_column("bookings", sa.Column("stripe_refund_id", sa.String(255), nullable=True))
    op.add_column("bookings", sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_bookings_stripe_payment_intent_id",
        "bookings",
        ["stripe_payment_intent_id"],
        unique=True,
    )

    op.execute("ALTER TABLE bookings DROP CONSTRAINT IF EXISTS ck_booking_status")
    op.create_check_constraint("ck_booking_status", "bookings", BOOKING_STATUS_CONSTRAINT)

    op.add_column("users", sa.Column("stripe_customer_id", sa.String(255), nullable=True))
    op.create_unique_constraint("uq_users_stripe_customer_id", "users", ["stripe_customer_id"])

    op.create_table(
        "stripe_events",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("booking_id", sa.String(64), nullable=True),
        sa.Column("processing_status", sa.String(30), nullable=False, server_default="processed"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_stripe_events_booking_id", "stripe_events", ["booking_id"])
    # Same posture as every other public table (see 20260714_0009 /
    # 20260908_0013): RLS on with no policies, so Supabase's auto-generated
    # REST API can't read it; the app's own connection is unaffected.
    op.execute("ALTER TABLE stripe_events ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_stripe_events_booking_id", table_name="stripe_events")
    op.drop_table("stripe_events")
    op.drop_constraint("uq_users_stripe_customer_id", "users", type_="unique")
    op.drop_column("users", "stripe_customer_id")
    op.execute("ALTER TABLE bookings DROP CONSTRAINT IF EXISTS ck_booking_status")
    op.create_check_constraint("ck_booking_status", "bookings", PRIOR_BOOKING_STATUS_CONSTRAINT)
    op.drop_index("ix_bookings_stripe_payment_intent_id", table_name="bookings")
    for column in (
        "paid_at",
        "stripe_refund_id",
        "refunded_amount_cents",
        "stripe_fee_cents",
        "amount_paid_cents",
        "stripe_payment_intent_id",
        "payment_status",
    ):
        op.drop_column("bookings", column)
