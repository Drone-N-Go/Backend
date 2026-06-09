"""Baseline schema for Render and Supabase.

Revision ID: 20260609_0001
Revises:
Create Date: 2026-06-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260609_0001"
down_revision = None
branch_labels = None
depends_on = None


BOOKING_STATUSES = (
    "reserved",
    "ready_for_pickup",
    "locker_opened",
    "case_verified",
    "before_photos_complete",
    "in_use",
    "return_started",
    "after_photos_complete",
    "return_locker_opened",
    "return_video_complete",
    "returned",
    "cancelled",
)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("school", sa.String(length=255), nullable=True),
        sa.Column("role", sa.String(length=20), server_default="user", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("role IN ('user', 'admin')", name="ck_users_role"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "locker_locations",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("campus_name", sa.String(length=255), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("latitude", sa.Double(), nullable=False),
        sa.Column("longitude", sa.Double(), nullable=False),
        sa.Column("landmarks", sa.Text(), nullable=True),
        sa.Column("building_name", sa.String(length=255), nullable=True),
        sa.Column("directions", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "login_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("identifier", sa.String(length=255), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("lockout_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_login_attempts_identifier", "login_attempts", ["identifier"])

    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"], unique=True)

    op.create_table(
        "locker_units",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("locker_locations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("unit_number", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="available", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('available', 'occupied', 'maintenance')", name="ck_locker_unit_status"),
        sa.UniqueConstraint("location_id", "unit_number", name="uq_locker_unit_location_number"),
    )
    op.create_index("ix_locker_units_location_id", "locker_units", ["location_id"])

    op.create_table(
        "drones",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("subtitle", sa.String(length=255), server_default="", nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("category", sa.String(length=50), server_default="professional", nullable=False),
        sa.Column("skill_level", sa.String(length=30), server_default="intermediate", nullable=False),
        sa.Column("serial_number", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="available", nullable=False),
        sa.Column("assigned_locker_location_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("locker_locations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("hourly_rate", sa.Numeric(10, 2), nullable=False),
        sa.Column("daily_rate", sa.Numeric(10, 2), nullable=False),
        sa.Column("rating", sa.Numeric(3, 2), server_default="0", nullable=False),
        sa.Column("review_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("image_urls", postgresql.ARRAY(sa.String()), server_default="{}", nullable=False),
        sa.Column("standout_features", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("included_items", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("rules", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("specs", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('available', 'rented', 'damaged', 'maintenance')", name="ck_drone_status"),
        sa.CheckConstraint("hourly_rate > 0", name="ck_drone_hourly_rate"),
        sa.CheckConstraint("daily_rate > 0", name="ck_drone_daily_rate"),
        sa.CheckConstraint("rating >= 0 AND rating <= 5", name="ck_drone_rating"),
        sa.CheckConstraint("review_count >= 0", name="ck_drone_review_count"),
    )
    op.create_index("ix_drones_serial_number", "drones", ["serial_number"], unique=True)

    op.create_table(
        "drone_favorites",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("drone_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("drones.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "drone_id", name="uq_drone_favorites_user_drone"),
    )
    op.create_index("ix_drone_favorites_user_id", "drone_favorites", ["user_id"])
    op.create_index("ix_drone_favorites_drone_id", "drone_favorites", ["drone_id"])

    op.create_table(
        "bookings",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("drone_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("drones.id", ondelete="CASCADE"), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("locker_locations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pickup_time", sa.String(length=50), nullable=False),
        sa.Column("rental_duration", sa.Integer(), nullable=False),
        sa.Column("rental_type", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="reserved", nullable=False),
        sa.Column("total_cost", sa.Numeric(10, 2), nullable=False),
        sa.Column("smiota_object_id", sa.String(length=255), nullable=True),
        sa.Column("smiota_passcode", sa.String(length=50), nullable=True),
        sa.Column("smiota_locker_name", sa.String(length=255), nullable=True),
        sa.Column("smiota_courier_code", sa.String(length=255), nullable=True),
        sa.Column("ready_for_pickup_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locker_opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("case_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("before_photos_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("in_use_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("return_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("after_photos_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("return_locker_opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("return_video_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("returned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(f"status IN {BOOKING_STATUSES}", name="ck_booking_status"),
        sa.CheckConstraint("rental_type IN ('hourly', 'daily')", name="ck_booking_rental_type"),
        sa.CheckConstraint("rental_duration > 0", name="ck_booking_rental_duration"),
    )
    op.create_index("ix_bookings_user_id", "bookings", ["user_id"])
    op.create_index("ix_bookings_drone_id", "bookings", ["drone_id"])
    op.create_index("ix_bookings_smiota_object_id", "bookings", ["smiota_object_id"])

    op.create_table(
        "damage_reports",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("booking_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("drone_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("drones.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pre_rental_images", postgresql.ARRAY(sa.String()), server_default="{}", nullable=False),
        sa.Column("post_rental_images", postgresql.ARRAY(sa.String()), server_default="{}", nullable=False),
        sa.Column("return_video_url", sa.Text(), nullable=True),
        sa.Column("return_video_uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("admin_notes", sa.Text(), nullable=True),
        sa.Column("condition_status", sa.String(length=20), server_default="needs_review", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("condition_status IN ('undamaged', 'damaged', 'needs_review')", name="ck_damage_condition"),
    )
    op.create_index("ix_damage_reports_booking_id", "damage_reports", ["booking_id"])

    op.create_table(
        "smiota_events",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("notification_type", sa.String(length=100), nullable=False),
        sa.Column("object_id", sa.String(length=255), nullable=False),
        sa.Column("locker_name", sa.String(length=255), nullable=True),
        sa.Column("passcode", sa.String(length=50), nullable=True),
        sa.Column("courier_code", sa.String(length=255), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=True),
        sa.Column("processed", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_smiota_events_object_id", "smiota_events", ["object_id"])


def downgrade() -> None:
    op.drop_table("smiota_events")
    op.drop_table("damage_reports")
    op.drop_table("bookings")
    op.drop_table("drone_favorites")
    op.drop_table("drones")
    op.drop_table("locker_units")
    op.drop_table("refresh_tokens")
    op.drop_table("login_attempts")
    op.drop_table("locker_locations")
    op.drop_table("users")
