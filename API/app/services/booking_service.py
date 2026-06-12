"""
app/services/booking_service.py
--------------------------------
Business logic for the full drone booking lifecycle:
  create → webhook events → passcode → return → damage review
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.booking import Booking
from app.models.damage_report import DamageReport
from app.models.drone import Drone
from app.models.locker_location import LockerLocation
from app.models.user import User
from app.core.booking_lifecycle import (
    BOOKING_STATUS_TIMESTAMP_FIELDS,
    BOOKING_TRANSITIONS,
    TERMINAL_BOOKING_STATUSES,
)
from app.schemas.booking import (
    BookingCreateRequest,
    BookingListResponse,
    BookingResponse,
    PasscodeResponse,
)
from app.services.case_qr_service import assert_active_case_qr_matches_booking
from app.services.drone_service import _drone_response

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

async def _get_booking_or_404(booking_id: str, db: AsyncSession) -> Booking:
    result = await db.execute(select(Booking).where(Booking.id == booking_id))
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found.")
    return booking


async def _get_booking_detail_or_404(booking_id: str, db: AsyncSession) -> Booking:
    result = await db.execute(
        select(Booking)
        .where(Booking.id == booking_id)
        .options(
            selectinload(Booking.drone).selectinload(Drone.assigned_location),
            selectinload(Booking.location),
            selectinload(Booking.damage_report),
        )
    )
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found.")
    return booking


def booking_response(booking: Booking, favorite_ids: set[str] | None = None) -> BookingResponse:
    location = None
    if booking.location:
        location = {
            "id": booking.location.id,
            "campus_name": booking.location.campus_name,
            "address": booking.location.address,
            "latitude": booking.location.latitude,
            "longitude": booking.location.longitude,
            "building_name": booking.location.building_name,
            "landmarks": booking.location.landmarks,
            "directions": booking.location.directions,
        }

    report = booking.damage_report
    response = BookingResponse.model_validate(booking)
    response.drone = _drone_response(booking.drone, favorite_ids).model_dump(mode="json") if booking.drone else None
    response.location = location
    response.pre_rental_images = list(report.pre_rental_images or []) if report else []
    response.post_rental_images = list(report.post_rental_images or []) if report else []
    response.return_video_url = report.return_video_url if report else None
    return response


def _assert_current_user_booking(booking: Booking, current_user: User) -> None:
    if booking.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this booking.",
        )


def _calculate_cost(drone: Drone, rental_type: str, duration: int) -> Decimal:
    if rental_type == "hourly":
        return Decimal(str(drone.hourly_rate)) * duration
    return Decimal(str(drone.daily_rate)) * duration


def _stamp_status_timestamp(booking: Booking, new_status: str) -> None:
    field_name = BOOKING_STATUS_TIMESTAMP_FIELDS.get(new_status)
    if field_name and getattr(booking, field_name) is None:
        setattr(booking, field_name, datetime.now(timezone.utc))


def _advance_booking_status(booking: Booking, target_status: str) -> Booking:
    if booking.status == target_status:
        return booking

    if booking.status in TERMINAL_BOOKING_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot advance a terminal booking with status '{booking.status}'.",
        )

    expected_status = BOOKING_TRANSITIONS[target_status]
    if booking.status != expected_status:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot move booking from '{booking.status}' to '{target_status}'. "
                f"Expected current status: '{expected_status}'."
            ),
        )

    booking.status = target_status
    _stamp_status_timestamp(booking, target_status)
    return booking


async def _get_damage_report(booking_id: str, db: AsyncSession) -> DamageReport | None:
    result = await db.execute(select(DamageReport).where(DamageReport.booking_id == booking_id))
    return result.scalar_one_or_none()


async def _ensure_damage_report(
    booking: Booking, current_user: User, db: AsyncSession
) -> DamageReport:
    report = await _get_damage_report(booking.id, db)
    if report:
        return report

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


def _assert_evidence(
    report: DamageReport | None,
    evidence_type: str,
    skip_evidence_check: bool,
) -> None:
    if skip_evidence_check:
        return

    has_evidence = False
    if evidence_type == "pre_rental":
        has_evidence = bool(report and report.pre_rental_images)
    elif evidence_type == "post_rental":
        has_evidence = bool(report and report.post_rental_images)
    elif evidence_type == "return_video":
        has_evidence = bool(report and report.return_video_url)

    if not has_evidence:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot complete {evidence_type} step before uploading required evidence.",
        )


async def _advance_and_flush(
    booking: Booking, target_status: str, db: AsyncSession
) -> Booking:
    _advance_booking_status(booking, target_status)
    db.add(booking)
    await db.flush()
    logger.info("Booking %s advanced to %s", booking.id, target_status)
    return booking


# --------------------------------------------------------------------------- #
# Create booking
# --------------------------------------------------------------------------- #

async def create_booking(
    body: BookingCreateRequest, current_user: User, db: AsyncSession
) -> Booking:
    # 1. Validate drone
    drone_result = await db.execute(select(Drone).where(Drone.id == body.drone_id))
    drone = drone_result.scalar_one_or_none()
    if not drone:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Drone not found.")
    if drone.status != "available":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Drone is not available for rental (current status: {drone.status}).",
        )

    # 2. Validate location
    loc_result = await db.execute(
        select(LockerLocation).where(LockerLocation.id == body.location_id)
    )
    if not loc_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Locker location not found."
        )

    # 3. Calculate cost
    total_cost = _calculate_cost(drone, body.rental_type, body.rental_duration)

    # 4. Create booking
    booking = Booking(
        user_id=current_user.id,
        drone_id=body.drone_id,
        location_id=body.location_id,
        pickup_time=body.pickup_time,
        rental_duration=body.rental_duration,
        rental_type=body.rental_type,
        total_cost=total_cost,
        status="reserved",
    )
    db.add(booking)

    # 5. Mark drone as rented (reserved)
    drone.status = "rented"
    db.add(drone)

    await db.flush()
    logger.info("Booking created: %s for user %s", booking.id, current_user.id)
    return booking


# --------------------------------------------------------------------------- #
# List bookings
# --------------------------------------------------------------------------- #

async def list_bookings(
    current_user: User,
    db: AsyncSession,
    status_filter: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> BookingListResponse:
    query = select(Booking)
    count_query = select(func.count()).select_from(Booking)

    query = query.where(Booking.user_id == current_user.id)
    count_query = count_query.where(Booking.user_id == current_user.id)

    if status_filter:
        query = query.where(Booking.status == status_filter)
        count_query = count_query.where(Booking.status == status_filter)

    total = (await db.execute(count_query)).scalar_one()
    bookings = (
        await db.execute(query.order_by(Booking.created_at.desc()).offset(skip).limit(limit))
    ).scalars().all()

    return BookingListResponse(
        items=[BookingResponse.model_validate(b) for b in bookings],
        total=total,
        skip=skip,
        limit=limit,
    )


# --------------------------------------------------------------------------- #
# Get single booking
# --------------------------------------------------------------------------- #

async def get_booking(
    booking_id: str, current_user: User, db: AsyncSession
) -> Booking:
    booking = await _get_booking_or_404(booking_id, db)
    _assert_current_user_booking(booking, current_user)
    return booking


async def get_booking_detail(
    booking_id: str, current_user: User, db: AsyncSession
) -> BookingResponse:
    booking = await _get_booking_detail_or_404(booking_id, db)
    _assert_current_user_booking(booking, current_user)
    return booking_response(booking)


async def get_active_booking(current_user: User, db: AsyncSession) -> BookingResponse | None:
    result = await db.execute(
        select(Booking)
        .where(
            Booking.user_id == current_user.id,
            Booking.status.notin_(TERMINAL_BOOKING_STATUSES),
        )
        .options(
            selectinload(Booking.drone).selectinload(Drone.assigned_location),
            selectinload(Booking.location),
            selectinload(Booking.damage_report),
        )
        .order_by(Booking.created_at.desc())
        .limit(1)
    )
    booking = result.scalar_one_or_none()
    return booking_response(booking) if booking else None


async def list_booking_history(
    current_user: User,
    db: AsyncSession,
    skip: int = 0,
    limit: int = 50,
) -> BookingListResponse:
    query = (
        select(Booking)
        .where(
            Booking.user_id == current_user.id,
            Booking.status.in_(TERMINAL_BOOKING_STATUSES),
        )
        .options(
            selectinload(Booking.drone).selectinload(Drone.assigned_location),
            selectinload(Booking.location),
            selectinload(Booking.damage_report),
        )
        .order_by(Booking.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    count_query = (
        select(func.count())
        .select_from(Booking)
        .where(
            Booking.user_id == current_user.id,
            Booking.status.in_(TERMINAL_BOOKING_STATUSES),
        )
    )

    total = (await db.execute(count_query)).scalar_one()
    bookings = (await db.execute(query)).scalars().all()
    return BookingListResponse(
        items=[booking_response(b) for b in bookings],
        total=total,
        skip=skip,
        limit=limit,
    )


# --------------------------------------------------------------------------- #
# Passcode retrieval
# --------------------------------------------------------------------------- #

async def get_passcode(
    booking_id: str, current_user: User, db: AsyncSession
) -> PasscodeResponse:
    booking = await _get_booking_or_404(booking_id, db)
    _assert_current_user_booking(booking, current_user)

    if not booking.smiota_passcode:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Passcode not yet available. The drone has not been deposited in the locker.",
        )

    return PasscodeResponse(
        booking_id=booking.id,
        passcode=booking.smiota_passcode,
        locker_name=booking.smiota_locker_name,
        courier_code=booking.smiota_courier_code,
    )


# --------------------------------------------------------------------------- #
# Cancel booking
# --------------------------------------------------------------------------- #

async def cancel_booking(
    booking_id: str, current_user: User, db: AsyncSession
) -> Booking:
    booking = await _get_booking_or_404(booking_id, db)
    _assert_current_user_booking(booking, current_user)

    if booking.status in TERMINAL_BOOKING_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot cancel a booking with status '{booking.status}'.",
        )

    booking.status = "cancelled"
    _stamp_status_timestamp(booking, "cancelled")
    db.add(booking)

    # Free the drone
    drone_result = await db.execute(select(Drone).where(Drone.id == booking.drone_id))
    drone = drone_result.scalar_one_or_none()
    if drone:
        drone.status = "available"
        db.add(drone)

    await db.flush()
    logger.info("Booking cancelled: %s", booking.id)
    return booking


# --------------------------------------------------------------------------- #
# Frontend-aligned lifecycle transitions
# --------------------------------------------------------------------------- #

async def mark_locker_opened(
    booking_id: str, current_user: User, db: AsyncSession
) -> Booking:
    booking = await _get_booking_or_404(booking_id, db)
    _assert_current_user_booking(booking, current_user)
    return await _advance_and_flush(booking, "locker_opened", db)


async def mark_case_verified(
    booking_id: str, qr_payload: str, current_user: User, db: AsyncSession
) -> Booking:
    booking = await _get_booking_or_404(booking_id, db)
    _assert_current_user_booking(booking, current_user)
    await assert_active_case_qr_matches_booking(booking, qr_payload, db)
    return await _advance_and_flush(booking, "case_verified", db)


async def complete_before_photos(
    booking_id: str,
    skip_evidence_check: bool,
    current_user: User,
    db: AsyncSession,
) -> Booking:
    booking = await _get_booking_or_404(booking_id, db)
    _assert_current_user_booking(booking, current_user)
    if booking.status != "before_photos_complete":
        report = await _get_damage_report(booking_id, db)
        _assert_evidence(report, "pre_rental", skip_evidence_check)
    return await _advance_and_flush(booking, "before_photos_complete", db)


async def start_use(
    booking_id: str, current_user: User, db: AsyncSession
) -> Booking:
    booking = await _get_booking_or_404(booking_id, db)
    _assert_current_user_booking(booking, current_user)
    return await _advance_and_flush(booking, "in_use", db)


async def start_return(
    booking_id: str, current_user: User, db: AsyncSession
) -> Booking:
    booking = await _get_booking_or_404(booking_id, db)
    _assert_current_user_booking(booking, current_user)
    return await _advance_and_flush(booking, "return_started", db)


async def mark_return_case_verified(
    booking_id: str, qr_payload: str, current_user: User, db: AsyncSession
) -> Booking:
    booking = await _get_booking_or_404(booking_id, db)
    _assert_current_user_booking(booking, current_user)
    await assert_active_case_qr_matches_booking(booking, qr_payload, db)
    return await _advance_and_flush(booking, "return_started", db)


async def complete_after_photos(
    booking_id: str,
    skip_evidence_check: bool,
    current_user: User,
    db: AsyncSession,
) -> Booking:
    booking = await _get_booking_or_404(booking_id, db)
    _assert_current_user_booking(booking, current_user)
    if booking.status != "after_photos_complete":
        report = await _get_damage_report(booking_id, db)
        _assert_evidence(report, "post_rental", skip_evidence_check)
    return await _advance_and_flush(booking, "after_photos_complete", db)


async def mark_return_locker_opened(
    booking_id: str, current_user: User, db: AsyncSession
) -> Booking:
    booking = await _get_booking_or_404(booking_id, db)
    _assert_current_user_booking(booking, current_user)
    return await _advance_and_flush(booking, "return_locker_opened", db)


async def complete_return_video(
    booking_id: str,
    skip_evidence_check: bool,
    current_user: User,
    db: AsyncSession,
) -> Booking:
    booking = await _get_booking_or_404(booking_id, db)
    _assert_current_user_booking(booking, current_user)
    if booking.status != "return_video_complete":
        report = await _get_damage_report(booking_id, db)
        _assert_evidence(report, "return_video", skip_evidence_check)
    return await _advance_and_flush(booking, "return_video_complete", db)


async def complete_return(
    booking_id: str, notes: str | None, current_user: User, db: AsyncSession
) -> Booking:
    booking = await _get_booking_or_404(booking_id, db)
    _assert_current_user_booking(booking, current_user)
    _advance_booking_status(booking, "returned")
    db.add(booking)

    # Determine drone status based on damage report
    drone_result = await db.execute(select(Drone).where(Drone.id == booking.drone_id))
    drone = drone_result.scalar_one_or_none()

    report = await _ensure_damage_report(booking, current_user, db)

    if notes:
        report.admin_notes = notes
        db.add(report)

    if report.condition_status == "damaged":
        if drone:
            drone.status = "damaged"
    else:
        if drone:
            drone.status = "available"

    if drone:
        db.add(drone)

    await db.flush()
    logger.info("Booking returned: %s", booking_id)
    return booking
