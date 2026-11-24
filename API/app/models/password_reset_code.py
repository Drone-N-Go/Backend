"""
app/models/password_reset_code.py
---------------------------------
One-time codes for the "forgot password" flow (added 2026-11-24).

Shared by the admin apps (iOS, Android, web portal) and the consumer apps,
since admins and renters are both rows in `users`.

A 6-digit code is emailed to the user. Only an HMAC of the code is stored
(keyed with SECRET_KEY and bound to the user id), so a database leak does not
reveal usable codes. A code is single-use, expires after
PASSWORD_RESET_CODE_TTL_MINUTES, and is burned after
PASSWORD_RESET_MAX_CODE_ATTEMPTS wrong guesses.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PasswordResetCode(Base):
    __tablename__ = "password_reset_codes"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Set when the code is used successfully OR invalidated (superseded by a
    # newer code, too many wrong guesses, or another code was used).
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
