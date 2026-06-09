"""
app/models/damage_report.py
-----------------------------
ORM model for the `damage_reports` table.
Stores pre/post-rental images (as S3 URLs) and condition status.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DamageReport(Base):
    __tablename__ = "damage_reports"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    booking_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("bookings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    drone_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("drones.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Arrays of S3 URLs
    pre_rental_images: Mapped[list] = mapped_column(
        ARRAY(String), nullable=False, server_default="{}"
    )
    post_rental_images: Mapped[list] = mapped_column(
        ARRAY(String), nullable=False, server_default="{}"
    )
    return_video_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    return_video_uploaded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    admin_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    condition_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="needs_review", server_default="needs_review"
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
            "condition_status IN ('undamaged', 'damaged', 'needs_review')",
            name="ck_damage_condition",
        ),
    )

    # Relationships
    booking: Mapped["Booking"] = relationship("Booking", back_populates="damage_report")  # noqa: F821
