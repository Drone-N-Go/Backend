"""
app/models/maintenance_task.py
------------------------------
Admin maintenance and support tasks for lockers and drones.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class MaintenanceTask(Base):
    __tablename__ = "maintenance_tasks"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    location_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("locker_locations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    locker_unit_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("locker_units.id", ondelete="SET NULL"), nullable=True, index=True
    )
    drone_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("drones.id", ondelete="SET NULL"), nullable=True, index=True
    )
    assigned_admin_profile_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("admin_profiles.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by_admin_profile_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("admin_profiles.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="open", server_default="open")
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="normal", server_default="normal")
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint("status IN ('open', 'in_progress', 'resolved', 'cancelled')", name="ck_maintenance_status"),
        CheckConstraint("priority IN ('low', 'normal', 'high', 'urgent')", name="ck_maintenance_priority"),
    )

    location: Mapped["LockerLocation | None"] = relationship("LockerLocation", lazy="select")  # noqa: F821
    locker_unit: Mapped["LockerUnit | None"] = relationship("LockerUnit", lazy="select")  # noqa: F821
    drone: Mapped["Drone | None"] = relationship("Drone", lazy="select")  # noqa: F821
    assigned_admin_profile: Mapped["AdminProfile | None"] = relationship(  # noqa: F821
        "AdminProfile", foreign_keys=[assigned_admin_profile_id], lazy="select"
    )
    created_by_admin_profile: Mapped["AdminProfile | None"] = relationship(  # noqa: F821
        "AdminProfile", foreign_keys=[created_by_admin_profile_id], lazy="select"
    )
