"""
app/models/admin_profile.py
---------------------------
Admin authorization profile linked to a normal user identity.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


ADMIN_ROLES = ("owner", "master_developer", "manager", "developer", "admin")
ADMIN_STATUSES = ("active", "suspended")


class AdminProfile(Base):
    __tablename__ = "admin_profiles"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
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
        CheckConstraint(
            f"role IN {ADMIN_ROLES}",
            name="ck_admin_profiles_role",
        ),
        CheckConstraint(
            f"status IN {ADMIN_STATUSES}",
            name="ck_admin_profiles_status",
        ),
    )

    user: Mapped["User"] = relationship("User", lazy="select")  # noqa: F821
    location_assignments: Mapped[list["AdminLocationAssignment"]] = relationship(  # noqa: F821
        "AdminLocationAssignment",
        back_populates="admin_profile",
        cascade="all, delete-orphan",
    )


class AdminLocationAssignment(Base):
    __tablename__ = "admin_location_assignments"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    admin_profile_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("admin_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    location_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("locker_locations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "admin_profile_id",
            "location_id",
            name="uq_admin_location_assignment_profile_location",
        ),
    )

    admin_profile: Mapped["AdminProfile"] = relationship(  # noqa: F821
        "AdminProfile", back_populates="location_assignments"
    )
    location: Mapped["LockerLocation"] = relationship("LockerLocation", lazy="select")  # noqa: F821
