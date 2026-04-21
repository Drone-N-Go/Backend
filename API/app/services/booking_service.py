"""
app/services/booking_service.py
--------------------------------
Business logic for the full drone booking lifecycle:
  create → link smiota → webhook events → passcode → return → damage review
"""

import logging
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import Booking
from app.models.damage_report import DamageReport
from app.models.drone import Drone
from app.models.locker_location import LockerLocation
from app.models.user import User
from app.schemas.booking import (
    BookingCreateRequest,
    BookingListResponse,
    BookingResponse,
    PasscodeResponse,
)

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


def _assert_booking_owner_or_admin(booking: Booking, current_user: User) -> None:
    if current_user.role != "admin" and booking.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this booking.",
        )


def _calculate_cost(drone: Drone, rental_type: str, duration: int) -> Decimal:
    if rental_type == "hourly":
        return Decimal(str(drone.hourly_rate)) * duration
    return Decimal(str(drone.daily_rate)) * duration


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
        status="pending",
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

    # Non-admins only see their own bookings
    if current_user.role != "admin":
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
    _assert_booking_owner_or_admin(booking, current_user)
    return booking


# --------------------------------------------------------------------------- #
# Passcode retrieval
# --------------------------------------------------------------------------- #

async def get_passcode(
    booking_id: str, current_user: User, db: AsyncSession
) -> PasscodeResponse:
    booking = await _get_booking_or_404(booking_id, db)
    _assert_booking_owner_or_admin(booking, current_user)

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
    _assert_booking_owner_or_admin(booking, current_user)

    if booking.status in ("completed", "cancelled"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot cancel a booking with status '{booking.status}'.",
        )

    booking.status = "cancelled"
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
# Admin: update booking status
# --------------------------------------------------------------------------- #

async def update_booking_status(
    booking_id: str, new_status: str, db: AsyncSession
) -> Booking:
    booking = await _get_booking_or_404(booking_id, db)
    booking.status = new_status
    db.add(booking)
    await db.flush()
    return booking


# --------------------------------------------------------------------------- #
# Admin: link Smiota object ID
# --------------------------------------------------------------------------- #

async def link_smiota_object(
    booking_id: str, smiota_object_id: str, db: AsyncSession
) -> Booking:
    booking = await _get_booking_or_404(booking_id, db)
    booking.smiota_object_id = smiota_object_id
    db.add(booking)
    await db.flush()
    logger.info("Smiota object %s linked to booking %s", smiota_object_id, booking_id)
    return booking


# --------------------------------------------------------------------------- #
# Return drone
# --------------------------------------------------------------------------- #

async def return_drone(
    booking_id: str, notes: str | None, current_user: User, db: AsyncSession
) -> Booking:
    booking = await _get_booking_or_404(booking_id, db)
    _assert_booking_owner_or_admin(booking, current_user)

    if booking.status not in ("pending", "active"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot return a booking with status '{booking.status}'.",
        )

    booking.status = "completed"
    db.add(booking)

    # Determine drone status based on damage report
    drone_result = await db.execute(select(Drone).where(Drone.id == booking.drone_id))
    drone = drone_result.scalar_one_or_none()

    report_result = await db.execute(
        select(DamageReport).where(DamageReport.booking_id == booking_id)
    )
    report = report_result.scalar_one_or_none()

    if report:
        if report.condition_status == "damaged":
            if drone:
                drone.status = "damaged"
        else:
            # undamaged or needs_review → make available
            if drone:
                drone.status = "available"
    else:
        # No report → create a needs_review record and make drone available
        new_report = DamageReport(
            booking_id=booking_id,
            user_id=current_user.id,
            drone_id=booking.drone_id,
            pre_rental_images=[],
            post_rental_images=[],
            admin_notes=notes,
            condition_status="needs_review",
        )
        db.add(new_report)
        if drone:
            drone.status = "available"

    if drone:
        db.add(drone)

    await db.flush()
    logger.info("Booking returned: %s", booking_id)
    return booking
