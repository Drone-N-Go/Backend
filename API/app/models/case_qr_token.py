"""
app/models/case_qr_token.py
---------------------------
Opaque QR tokens printed inside physical drone cases.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


CASE_QR_TOKEN_STATUSES = ("pending_printed", "active", "voided", "rotated")


class CaseQRToken(Base):
    __tablename__ = "case_qr_tokens"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    drone_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("drones.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    encrypted_token: Mapped[str] = mapped_column(Text, nullable=False)
    payload_prefix: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="https://droneandgo.io/case/",
        server_default="https://droneandgo.io/case/",
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending_printed", server_default="pending_printed", index=True
    )
    created_by_admin_profile_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("admin_profiles.id", ondelete="SET NULL"), nullable=True
    )
    confirmed_by_admin_profile_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("admin_profiles.id", ondelete="SET NULL"), nullable=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            f"status IN {CASE_QR_TOKEN_STATUSES}",
            name="ck_case_qr_tokens_status",
        ),
    )

    drone: Mapped["Drone"] = relationship("Drone")  # noqa: F821
