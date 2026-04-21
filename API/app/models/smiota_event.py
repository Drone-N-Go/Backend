"""
app/models/smiota_event.py
---------------------------
ORM model for the `smiota_events` table.
Raw event log from Smiota webhook payloads.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SmiotaEvent(Base):
    __tablename__ = "smiota_events"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    notification_type: Mapped[str] = mapped_column(String(100), nullable=False)
    object_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    locker_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    passcode: Mapped[str | None] = mapped_column(String(50), nullable=True)
    courier_code: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    processed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
