"""
app/models/contact_submission.py
-----------------------------------
ORM model for the `contact_submissions` table.

Backstop record for the public website contact form (see
app/api/routers/contact.py). The row is written BEFORE the Resend
notification email is attempted, and the email attempt never rolls it back
-- so a submission is never lost even if Resend is down, the API key is
bad, or the account has a billing problem. `email_sent` records whether the
notification actually went out; a row with `email_sent = false` is one
nobody has seen yet and is the thing to check for if messages seem to have
stopped arriving.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ContactSubmission(Base):
    __tablename__ = "contact_submissions"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    email_sent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
