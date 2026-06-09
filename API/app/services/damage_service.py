"""
app/services/damage_service.py
-------------------------------
Business logic for drone damage reports:
  - Pre/post-rental image uploads (to S3)
  - Admin condition review
"""

import logging
from datetime import datetime, timezone

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import Booking
from app.models.damage_report import DamageReport
from app.models.drone import Drone
from app.models.user import User
from app.schemas.damage import (
    BookingImagesResponse,
    DamageReportResponse,
    ImageUploadResponse,
    ReturnVideoUploadResponse,
)
from app.services.s3_service import upload_images, upload_video

logger = logging.getLogger(__name__)


async def _get_booking_for_user(
    booking_id: str, current_user: User, db: AsyncSession
) -> Booking:
    result = await db.execute(select(Booking).where(Booking.id == booking_id))
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found.")
    if current_user.role != "admin" and booking.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    return booking


async def _get_or_create_report(
    booking: Booking, current_user: User, db: AsyncSession
) -> DamageReport:
    result = await db.execute(
        select(DamageReport).where(DamageReport.booking_id == booking.id)
    )
    report = result.scalar_one_or_none()
    if not report:
        report = DamageReport(
            booking_id=booking.id,
            user_id=current_user.id,
            drone_id=booking.drone_id,
            pre_rental_images=[],
            post_rental_images=[],
            condition_status="needs_review",
        )
        db.add(report)
        await db.flush()
    return report


def _assert_status(booking: Booking, allowed_statuses: set[str], action: str) -> None:
    if booking.status not in allowed_statuses:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot {action} while booking status is '{booking.status}'. "
                f"Allowed statuses: {', '.join(sorted(allowed_statuses))}."
            ),
        )


async def upload_pre_rental_images(
    booking_id: str,
    files: list[UploadFile],
    current_user: User,
    db: AsyncSession,
) -> ImageUploadResponse:
    booking = await _get_booking_for_user(booking_id, current_user, db)
    _assert_status(booking, {"case_verified", "before_photos_complete"}, "upload pre-rental images")
    report = await _get_or_create_report(booking, current_user, db)

    urls = await upload_images(files, folder=f"drone-images/pre-rental/{booking_id}")

    report.pre_rental_images = list(report.pre_rental_images or []) + urls
    db.add(report)
    await db.flush()

    logger.info("Uploaded %d pre-rental images for booking %s", len(urls), booking_id)

    return ImageUploadResponse(
        booking_id=booking_id,
        image_type="pre_rental",
        uploaded_urls=urls,
        damage_report=DamageReportResponse.model_validate(report),
    )


async def upload_post_rental_images(
    booking_id: str,
    files: list[UploadFile],
    current_user: User,
    db: AsyncSession,
) -> ImageUploadResponse:
    booking = await _get_booking_for_user(booking_id, current_user, db)
    _assert_status(booking, {"return_started", "after_photos_complete"}, "upload post-rental images")
    report = await _get_or_create_report(booking, current_user, db)

    urls = await upload_images(files, folder=f"drone-images/post-rental/{booking_id}")

    report.post_rental_images = list(report.post_rental_images or []) + urls
    db.add(report)
    await db.flush()

    logger.info("Uploaded %d post-rental images for booking %s", len(urls), booking_id)

    return ImageUploadResponse(
        booking_id=booking_id,
        image_type="post_rental",
        uploaded_urls=urls,
        damage_report=DamageReportResponse.model_validate(report),
    )


async def upload_return_video(
    booking_id: str,
    file: UploadFile,
    current_user: User,
    db: AsyncSession,
) -> ReturnVideoUploadResponse:
    booking = await _get_booking_for_user(booking_id, current_user, db)
    _assert_status(booking, {"return_locker_opened", "return_video_complete"}, "upload return video")
    report = await _get_or_create_report(booking, current_user, db)

    url = await upload_video(file, folder=f"drone-videos/return/{booking_id}")
    report.return_video_url = url
    report.return_video_uploaded_at = datetime.now(timezone.utc)
    db.add(report)
    await db.flush()

    logger.info("Uploaded return video for booking %s", booking_id)

    return ReturnVideoUploadResponse(
        booking_id=booking_id,
        return_video_url=url,
        damage_report=DamageReportResponse.model_validate(report),
    )


async def get_booking_images(
    booking_id: str, current_user: User, db: AsyncSession
) -> BookingImagesResponse:
    booking = await _get_booking_for_user(booking_id, current_user, db)

    result = await db.execute(
        select(DamageReport).where(DamageReport.booking_id == booking.id)
    )
    report = result.scalar_one_or_none()

    return BookingImagesResponse(
        booking_id=booking_id,
        pre_rental_images=report.pre_rental_images if report else [],
        post_rental_images=report.post_rental_images if report else [],
        return_video_url=report.return_video_url if report else None,
    )


async def admin_update_condition(
    drone_id: str,
    condition_status: str,
    admin_notes: str | None,
    db: AsyncSession,
) -> dict:
    """
    Admin reviews a drone's condition.
    Updates all 'needs_review' damage reports for this drone and sets drone status.
    """
    # Fetch drone
    drone_result = await db.execute(select(Drone).where(Drone.id == drone_id))
    drone = drone_result.scalar_one_or_none()
    if not drone:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Drone not found.")

    # Update all needs_review reports for this drone
    reports_result = await db.execute(
        select(DamageReport).where(
            DamageReport.drone_id == drone_id,
            DamageReport.condition_status == "needs_review",
        )
    )
    reports = reports_result.scalars().all()

    for report in reports:
        report.condition_status = condition_status
        if admin_notes:
            report.admin_notes = admin_notes
        db.add(report)

    # Set drone status based on condition
    if condition_status == "undamaged":
        drone.status = "available"
    elif condition_status == "damaged":
        drone.status = "damaged"
    else:  # needs_review
        drone.status = "maintenance"

    db.add(drone)
    await db.flush()

    logger.info(
        "Admin reviewed drone %s: condition=%s, reports_updated=%d",
        drone_id,
        condition_status,
        len(reports),
    )

    return {
        "drone_id": drone_id,
        "new_drone_status": drone.status,
        "condition_status": condition_status,
        "reports_updated": len(reports),
    }
