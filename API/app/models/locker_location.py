"""
app/models/locker_location.py
------------------------------
ORM model for the `locker_locations` table.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Double, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class LockerLocation(Base):
    __tablename__ = "locker_locations"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    campus_name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    latitude: Mapped[float] = mapped_column(Double, nullable=False)
    longitude: Mapped[float] = mapped_column(Double, nullable=False)
    landmarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    building_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    directions: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    units: Mapped[list["LockerUnit"]] = relationship(  # noqa: F821
        "LockerUnit", back_populates="location", cascade="all, delete-orphan", lazy="select"
    )
    drones: Mapped[list["Drone"]] = relationship(  # noqa: F821
        "Drone", back_populates="assigned_location", lazy="select"
    )
    bookings: Mapped[list["Booking"]] = relationship(  # noqa: F821
        "Booking", back_populates="location", lazy="select"
    )
