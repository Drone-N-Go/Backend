"""
app/models/locker_access_event.py
---------------------------------
Audited passcode reveal and locker-access events.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class LockerAccessEvent(Base):
    __tablename__ = "locker_access_events"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    admin_profile_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("admin_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    locker_unit_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("locker_units.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    drone_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("drones.id", ondelete="SET NULL"), nullable=True
    )
    booking_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("bookings.id", ondelete="SET NULL"), nullable=True
    )
    smiota_event_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("smiota_events.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    app_context: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    admin_profile: Mapped["AdminProfile"] = relationship("AdminProfile", lazy="select")  # noqa: F821
    locker_unit: Mapped["LockerUnit"] = relationship("LockerUnit", lazy="select")  # noqa: F821
    drone: Mapped["Drone | None"] = relationship("Drone", lazy="select")  # noqa: F821
    booking: Mapped["Booking | None"] = relationship("Booking", lazy="select")  # noqa: F821
    smiota_event: Mapped["SmiotaEvent | None"] = relationship("SmiotaEvent", lazy="select")  # noqa: F821
