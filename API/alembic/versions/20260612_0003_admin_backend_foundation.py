"""Admin backend foundation.

Revision ID: 20260612_0003
Revises: 20260609_0002
Create Date: 2026-06-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260612_0003"
down_revision = "20260609_0002"
branch_labels = None
depends_on = None


ADMIN_ROLES = ("owner", "master_developer", "manager", "developer", "admin")


def upgrade() -> None:
    op.add_column(
        "locker_units",
        sa.Column("current_drone_id", postgresql.UUID(as_uuid=False), nullable=True),
    )
    op.add_column("locker_units", sa.Column("smiota_locker_name", sa.String(length=255), nullable=True))
    op.add_column("locker_units", sa.Column("smiota_unit_identifier", sa.String(length=255), nullable=True))
    op.add_column(
        "locker_units",
        sa.Column("smiota_metadata", postgresql.JSONB(), server_default="{}", nullable=False),
    )
    op.create_foreign_key(
        "fk_locker_units_current_drone_id_drones",
        "locker_units",
        "drones",
        ["current_drone_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_locker_units_current_drone_id", "locker_units", ["current_drone_id"], unique=True)
    op.create_index("ix_locker_units_smiota_locker_name", "locker_units", ["smiota_locker_name"])
    op.create_index("ix_locker_units_smiota_unit_identifier", "locker_units", ["smiota_unit_identifier"])

    op.create_table(
        "admin_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("title", sa.String(length=100), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(f"role IN {ADMIN_ROLES}", name="ck_admin_profiles_role"),
        sa.CheckConstraint("status IN ('active', 'suspended')", name="ck_admin_profiles_status"),
    )
    op.create_index("ix_admin_profiles_user_id", "admin_profiles", ["user_id"], unique=True)

    op.create_table(
        "admin_location_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, nullable=False),
        sa.Column(
            "admin_profile_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("admin_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "location_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("locker_locations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "admin_profile_id",
            "location_id",
            name="uq_admin_location_assignment_profile_location",
        ),
    )
    op.create_index("ix_admin_location_assignments_admin_profile_id", "admin_location_assignments", ["admin_profile_id"])
    op.create_index("ix_admin_location_assignments_location_id", "admin_location_assignments", ["location_id"])

    op.create_table(
        "admin_audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, nullable=False),
        sa.Column(
            "admin_profile_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("admin_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("resource_type", sa.String(length=100), nullable=True),
        sa.Column("resource_id", sa.String(length=255), nullable=True),
        sa.Column("details", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_admin_audit_events_action", "admin_audit_events", ["action"])
    op.create_index("ix_admin_audit_events_admin_profile_id", "admin_audit_events", ["admin_profile_id"])

    op.create_table(
        "maintenance_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("locker_locations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("locker_unit_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("locker_units.id", ondelete="SET NULL"), nullable=True),
        sa.Column("drone_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("drones.id", ondelete="SET NULL"), nullable=True),
        sa.Column(
            "assigned_admin_profile_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("admin_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by_admin_profile_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("admin_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), server_default="open", nullable=False),
        sa.Column("priority", sa.String(length=20), server_default="normal", nullable=False),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('open', 'in_progress', 'resolved', 'cancelled')", name="ck_maintenance_status"),
        sa.CheckConstraint("priority IN ('low', 'normal', 'high', 'urgent')", name="ck_maintenance_priority"),
    )
    op.create_index("ix_maintenance_tasks_location_id", "maintenance_tasks", ["location_id"])
    op.create_index("ix_maintenance_tasks_locker_unit_id", "maintenance_tasks", ["locker_unit_id"])
    op.create_index("ix_maintenance_tasks_drone_id", "maintenance_tasks", ["drone_id"])
    op.create_index("ix_maintenance_tasks_assigned_admin_profile_id", "maintenance_tasks", ["assigned_admin_profile_id"])

    op.create_table(
        "locker_access_events",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, nullable=False),
        sa.Column(
            "admin_profile_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("admin_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "locker_unit_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("locker_units.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("drone_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("drones.id", ondelete="SET NULL"), nullable=True),
        sa.Column("booking_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("bookings.id", ondelete="SET NULL"), nullable=True),
        sa.Column(
            "smiota_event_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("smiota_events.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("app_context", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_locker_access_events_admin_profile_id", "locker_access_events", ["admin_profile_id"])
    op.create_index("ix_locker_access_events_locker_unit_id", "locker_access_events", ["locker_unit_id"])


def downgrade() -> None:
    op.drop_table("locker_access_events")
    op.drop_table("maintenance_tasks")
    op.drop_table("admin_audit_events")
    op.drop_table("admin_location_assignments")
    op.drop_table("admin_profiles")

    op.drop_index("ix_locker_units_smiota_unit_identifier", table_name="locker_units")
    op.drop_index("ix_locker_units_smiota_locker_name", table_name="locker_units")
    op.drop_index("ix_locker_units_current_drone_id", table_name="locker_units")
    op.drop_constraint("fk_locker_units_current_drone_id_drones", "locker_units", type_="foreignkey")
    op.drop_column("locker_units", "smiota_metadata")
    op.drop_column("locker_units", "smiota_unit_identifier")
    op.drop_column("locker_units", "smiota_locker_name")
    op.drop_column("locker_units", "current_drone_id")
