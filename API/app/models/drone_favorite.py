"""
User drone favorites.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DroneFavorite(Base):
    __tablename__ = "drone_favorites"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    drone_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("drones.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("user_id", "drone_id", name="uq_drone_favorites_user_drone"),
    )

    user: Mapped["User"] = relationship("User", back_populates="favorite_drones")  # noqa: F821
    drone: Mapped["Drone"] = relationship("Drone", back_populates="favorites")  # noqa: F821
