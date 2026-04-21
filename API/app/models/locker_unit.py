"""
app/models/locker_unit.py
--------------------------
ORM model for the `locker_units` table.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class LockerUnit(Base):
    __tablename__ = "locker_units"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    location_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("locker_locations.id", ondelete="CASCADE"),
        nullable=False,
    )
    unit_number: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="available", server_default="available"
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
        UniqueConstraint("location_id", "unit_number", name="uq_locker_unit_location_number"),
        CheckConstraint(
            "status IN ('available', 'occupied', 'maintenance')", name="ck_locker_unit_status"
        ),
    )

    # Relationships
    location: Mapped["LockerLocation"] = relationship(  # noqa: F821
        "LockerLocation", back_populates="units"
    )
