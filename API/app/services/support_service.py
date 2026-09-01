"""
app/services/support_service.py
----------------------------------
Business logic for freeform user-submitted support/damage reports.
See app/models/support_report.py for how this differs from DamageReport.
"""

import logging

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import Booking
from app.models.support_report import SupportReport
from app.models.user import User
from app.services.s3_service import upload_images

logger = logging.getLogger(__name__)


async def create_support_report(
    booking_id: str,
    description: str,
    files: list[UploadFile],
    current_user: User,
    db: AsyncSession,
) -> SupportReport:
    result = await db.execute(
        select(Booking).where(
            Booking.id == booking_id, Booking.user_id == current_user.id
        )
    )
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found.",
        )

    image_urls: list[str] = []
    if files:
        image_urls = await upload_images(files, folder=f"support-reports/{booking_id}")

    report = SupportReport(
        user_id=current_user.id,
        booking_id=booking_id,
        description=description,
        image_urls=image_urls,
    )
    db.add(report)
    await db.flush()

    logger.info("Support report %s created for booking %s", report.id, booking_id)
    return report
