"""
app/services/booking_service.py
--------------------------------
Business logic for the full drone booking lifecycle:
  create → webhook events → passcode → return → damage review
"""

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.booking import Booking
from app.models.damage_report import DamageReport
from app.models.drone import Drone
from app.models.locker_location import LockerLocation
from app.models.locker_unit import LockerUnit
from app.models.user import User
from app.core.booking_lifecycle import (
    BOOKING_STATUS_TIMESTAMP_FIELDS,
    BOOKING_TRANSITIONS,
    CANCELLATION_FREE_WINDOW_HOURS,
    CANCELLATION_GRACE_PERIOD_HOURS,
    NO_SHOW_REPEAT_THRESHOLD,
    NO_SHOW_REPEAT_WINDOW_DAYS,
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
    return await _auto_expire_if_overdue(booking, db)


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
    return await _auto_expire_if_overdue(booking, db)


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
    # Validate from the raw column values only — NOT the ORM object itself.
    # `Booking.drone`/`Booking.location` are SQLAlchemy relationships that
    # resolve to `Drone`/`LockerLocation` instances, but `BookingResponse`
    # declares those fields as `dict[str, Any]`. Calling
    # `BookingResponse.model_validate(booking)` directly makes Pydantic try
    # to validate those ORM objects against a plain-dict type and raise a
    # ValidationError (uncaught -> 500) on every booking that has a drone or
    # location attached, i.e. every real booking. Building from just the
    # table's columns sidesteps the relationship attributes entirely; the
    # drone/location/evidence fields are set explicitly below as before.
    column_data = {c.name: getattr(booking, c.name) for c in Booking.__table__.columns}
    response = BookingResponse.model_validate(column_data)
    response.drone = _drone_response(booking.drone, favorite_ids).model_dump(mode="json") if booking.drone else None
    response.location = location
    response.pre_rental_images = list(report.pre_rental_images or []) if report else []
    response.post_rental_images = list(report.post_rental_images or []) if report else []
    response.return_video_url = report.return_video_url if report else None
    response.is_cancellable = (
        booking.status not in TERMINAL_BOOKING_STATUSES and _is_cancellable(booking)
    )
    response.is_surrenderable = _is_overdue_never_picked_up(booking)
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


def _parse_pickup_time(pickup_time: str) -> datetime | None:
    """Best-effort parse of the free-form `pickup_time` string column.

    `pickup_time` is stored as a plain String(50), not a DateTime column (see
    app/models/booking.py) — the API contract documents it as an ISO 8601
    string but nothing enforces that at the DB layer. Returns None on any
    parse failure so callers can fail safe rather than 500 on bad data.
    """
    try:
        # datetime.fromisoformat() only accepts a trailing 'Z' from Python
        # 3.11 onward; this backend targets 3.10 in some environments (no
        # pinned runtime version — see render.yaml), so normalize it first
        # rather than assume a newer stdlib.
        normalized = pickup_time.strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        parsed = datetime.fromisoformat(normalized)
    except (TypeError, ValueError, AttributeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _is_cancellable(booking: Booking) -> bool:
    """Whether `booking` can still be cancelled online right now.

    Rule (confirmed with product 2026-09-01, for the web booking-cancel flow):
      - A booking whose pickup is at least CANCELLATION_FREE_WINDOW_HOURS away
        can always be cancelled.
      - A booking whose pickup is already inside that window (i.e. it was
        booked last-minute) can still be cancelled, but only within
        CANCELLATION_GRACE_PERIOD_HOURS of when it was *created* — after that
        it's locked in.
    Terminal bookings (already returned/cancelled) are never cancellable;
    callers that also need that check should test TERMINAL_BOOKING_STATUSES
    separately since this helper only evaluates the time-window rule.
    """
    now = datetime.now(timezone.utc)

    pickup_dt = _parse_pickup_time(booking.pickup_time)
    if pickup_dt is None:
        # Can't evaluate the window on unparseable data — fail open rather
        # than trap a user with a booking they can never cancel.
        return True

    if pickup_dt - now >= timedelta(hours=CANCELLATION_FREE_WINDOW_HOURS):
        return True

    created_at = booking.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return now - created_at <= timedelta(hours=CANCELLATION_GRACE_PERIOD_HOURS)


# --------------------------------------------------------------------------- #
# Surrender / no-show (never picked up before the return deadline passed)
# --------------------------------------------------------------------------- #

# Statuses in which the drone was never actually removed from the locker —
# the user scanned nothing and opened nothing. `_is_cancellable`/cancel_booking
# already cover the voluntary-cancel path; this is the separate "you never
# showed up and now it's overdue" path, which cancel_booking deliberately
# blocks once the pickup window rule locks a booking in.
NEVER_PICKED_UP_STATUSES = ("reserved", "ready_for_pickup")


def _compute_return_deadline(booking: Booking) -> datetime | None:
    """When this booking's rental window ends, or None if pickup_time can't
    be parsed (see _parse_pickup_time's docstring re: the loose String(50)
    column). Mirrors the client-side dropOffTime math in APIDTOs.swift
    (pickup_time + rental_duration, in hours for "hourly" / days for "daily")
    so the server and app agree on when a booking becomes overdue.
    """
    pickup_dt = _parse_pickup_time(booking.pickup_time)
    if pickup_dt is None:
        return None
    if booking.rental_type == "daily":
        return pickup_dt + timedelta(days=booking.rental_duration)
    return pickup_dt + timedelta(hours=booking.rental_duration)


def _is_overdue_never_picked_up(booking: Booking) -> bool:
    """True only if the booking is still pre-pickup (locker never opened)
    AND its return deadline has already passed. Unlike _is_cancellable,
    this fails CLOSED (returns False) when the deadline can't be computed —
    surrendering is a punitive, no-show-counting action, so an unparseable
    date should never be treated as "definitely overdue".
    """
    if booking.status not in NEVER_PICKED_UP_STATUSES:
        return False
    deadline = _compute_return_deadline(booking)
    if deadline is None:
        return False
    return datetime.now(timezone.utc) > deadline


async def _free_drone_and_locker(booking: Booking, db: AsyncSession) -> None:
    """Shared cleanup for the surrender / auto-expiry paths: release the
    drone back to inventory.

    BUG FIX (2026-09-08, same day this was introduced): this used to also
    clear LockerUnit.current_drone_id/current_passcode whenever it pointed
    at this drone. That's wrong here — a no-show by definition means the
    drone was NEVER removed from the locker, so it is still genuinely,
    physically sitting there. drone_service.list_drones()'s `status=available`
    filter requires BOTH Drone.status == "available" AND a live
    LockerUnit.current_drone_id match (see that function's comment) — clearing
    the FK made the drone permanently invisible to the consumer browse
    endpoint even after status flipped back to "available", since nothing
    (no future PackageDeposited webhook) would ever reset the pointer. Only
    the real "drone physically left the locker" event (the PackagePickedUp
    webhook) should ever clear that FK. This now matches cancel_booking(),
    which has always correctly left the locker alone and only frees the
    drone's status.
    """
    drone_result = await db.execute(select(Drone).where(Drone.id == booking.drone_id))
    drone = drone_result.scalar_one_or_none()
    if drone:
        drone.status = "available"
        db.add(drone)


async def _auto_expire_if_overdue(booking: Booking, db: AsyncSession) -> Booking:
    """Lazy server-side enforcement of the return deadline for a booking
    that was never picked up. There is no background job / cron
    infrastructure in this backend (confirmed: no Render cron service
    exists), so this can't fire the instant a deadline passes — instead it
    runs opportunistically on every read of a booking (get/list/detail/
    active), catching it up the next time anyone (the owning user, or an
    admin listing) looks at it. Safe to call unconditionally; no-ops unless
    _is_overdue_never_picked_up() is true.
    """
    if not _is_overdue_never_picked_up(booking):
        return booking
    booking.status = "no_show"
    _stamp_status_timestamp(booking, "no_show")
    db.add(booking)
    await _free_drone_and_locker(booking, db)
    await db.flush()
    logger.info("Booking %s auto-expired to no_show (deadline passed, never picked up)", booking.id)
    return booking


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


def _assert_evidence(report: DamageReport | None, evidence_type: str) -> None:
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
    # 0. Enforce one active (non-terminal) reservation per user. Matches
    #    the client-side rule the consumer apps already assume; enforced
    #    here so it can't be bypassed by calling the API directly.
    active_result = await db.execute(
        select(Booking).where(
            Booking.user_id == current_user.id,
            Booking.status.notin_(TERMINAL_BOOKING_STATUSES),
        )
    )
    if active_result.scalars().first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have an active reservation. Return or cancel it before booking another drone.",
        )

    # 0b. Repeat no-show policy: block new bookings once a user has racked up
    #     NO_SHOW_REPEAT_THRESHOLD `no_show` bookings within the trailing
    #     NO_SHOW_REPEAT_WINDOW_DAYS. This is the first automated enforcement
    #     of any kind in this backend (no penalties exist for late returns
    #     either) — deliberately scoped narrow to the no-show case per
    #     product direction, not a general strikes system.
    no_show_window_start = datetime.now(timezone.utc) - timedelta(days=NO_SHOW_REPEAT_WINDOW_DAYS)
    no_show_count_result = await db.execute(
        select(func.count())
        .select_from(Booking)
        .where(
            Booking.user_id == current_user.id,
            Booking.status == "no_show",
            Booking.no_show_at.isnot(None),
            Booking.no_show_at >= no_show_window_start,
        )
    )
    if no_show_count_result.scalar_one() >= NO_SHOW_REPEAT_THRESHOLD:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"You've missed pickup on {NO_SHOW_REPEAT_THRESHOLD} or more reservations in the "
                f"last {NO_SHOW_REPEAT_WINDOW_DAYS} days. New bookings are temporarily blocked — "
                "contact support if you think this is a mistake."
            ),
        )

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

    # 4. Look up whether this drone's locker already holds a passcode from a
    #    restock deposit (see webhook_service._handle_restock_deposit) — if
    #    so, this booking can go straight to "ready_for_pickup" since the
    #    drone is already physically in the locker.
    locker_unit_result = await db.execute(
        select(LockerUnit).where(LockerUnit.current_drone_id == drone.id)
    )
    locker_unit = locker_unit_result.scalar_one_or_none()

    # 5. Create booking
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

    if locker_unit and locker_unit.current_passcode:
        metadata = locker_unit.smiota_metadata or {}
        booking.smiota_passcode = locker_unit.current_passcode
        booking.smiota_locker_name = locker_unit.smiota_locker_name
        booking.smiota_courier_code = metadata.get("pending_deposit_courier_code")
        booking.smiota_object_id = metadata.get("pending_deposit_object_id")
        booking.status = "ready_for_pickup"
        booking.ready_for_pickup_at = datetime.now(timezone.utc)
        logger.info(
            "Booking for drone %s created ready-for-pickup — passcode already held on locker %s",
            drone.id,
            locker_unit.id,
        )

    db.add(booking)

    # 6. Mark drone as rented (reserved)
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
    query = select(Booking).options(
        selectinload(Booking.drone).selectinload(Drone.assigned_location),
        selectinload(Booking.location),
        selectinload(Booking.damage_report),
    )
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
    bookings = [await _auto_expire_if_overdue(b, db) for b in bookings]

    # Bug fix (2026-09-01): this previously called BookingResponse.model_validate(b)
    # directly on the ORM object, which raises a Pydantic ValidationError (-> 500)
    # on any booking with a drone/location attached, same class of bug already
    # fixed in booking_response() itself (see that function's docstring) — this
    # call site had just never been updated to use it. Also added the missing
    # eager-loading above so drone/location/damage_report are actually populated
    # here instead of triggering an async lazy-load error.
    return BookingListResponse(
        items=[booking_response(b) for b in bookings],
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
    if booking:
        booking = await _auto_expire_if_overdue(booking, db)
    if not booking:
        return None
    try:
        return booking_response(booking)
    except Exception as e:
        # TEMPORARY diagnostic — surfaces the real exception text through the
        # response body (the iOS app already displays whatever's in `detail`),
        # so it's visible without a curl round-trip or digging through Render
        # logs. Revert to a plain re-raise (or let it propagate uncaught)
        # once the real bug behind the "My Rental" 500 is found and fixed.
        logger.error("get_active_booking failed for booking %s: %s", booking.id, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{type(e).__name__}: {e}",
        )


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

    if booking.status not in {"ready_for_pickup", "locker_opened"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Passcode is only available during the pickup flow.",
        )

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

    if not _is_cancellable(booking):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This booking can no longer be cancelled online — pickup is within "
                f"{CANCELLATION_FREE_WINDOW_HOURS} hours and the "
                f"{CANCELLATION_GRACE_PERIOD_HOURS}-hour cancellation grace period has passed."
            ),
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
# Surrender booking (no-show — never picked up, deadline passed)
# --------------------------------------------------------------------------- #

async def surrender_booking(
    booking_id: str, current_user: User, db: AsyncSession
) -> Booking:
    """User-triggered counterpart to _auto_expire_if_overdue(): lets someone
    who reserved a drone but never opened the locker release it immediately
    once they're overdue, instead of it sitting locked until the next
    incidental read auto-expires it. Deliberately separate from
    cancel_booking() — that path is for voluntary, in-window cancellation and
    is intentionally time-gated to stop last-minute cancels; this path only
    opens up once you're *already* past the deadline and never checked out,
    which cancel_booking would otherwise permanently block (see
    CANCELLATION_FREE_WINDOW_HOURS/_is_cancellable).
    """
    booking = await _get_booking_or_404(booking_id, db)
    _assert_current_user_booking(booking, current_user)

    # _get_booking_or_404 already runs the same overdue check on every fetch
    # (see _auto_expire_if_overdue) — if it already flipped this booking to
    # no_show as part of *this same call*, treat that as success rather than
    # a conflict: the user got what they asked for.
    if booking.status == "no_show":
        return booking

    if booking.status in TERMINAL_BOOKING_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot surrender a booking with status '{booking.status}'.",
        )

    if booking.status not in NEVER_PICKED_UP_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The locker has already been opened for this booking — use the return flow "
                "(photos + video) instead of surrendering it."
            ),
        )

    deadline = _compute_return_deadline(booking)
    if deadline is None or datetime.now(timezone.utc) <= deadline:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This booking isn't overdue yet — surrender is only available once the return deadline has passed.",
        )

    booking.status = "no_show"
    _stamp_status_timestamp(booking, "no_show")
    db.add(booking)
    await _free_drone_and_locker(booking, db)
    await db.flush()
    logger.info("Booking surrendered as no-show: %s", booking.id)
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
    _skip_evidence_check: bool,
    current_user: User,
    db: AsyncSession,
) -> Booking:
    booking = await _get_booking_or_404(booking_id, db)
    _assert_current_user_booking(booking, current_user)
    if booking.status != "before_photos_complete":
        report = await _get_damage_report(booking_id, db)
        _assert_evidence(report, "pre_rental")
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
    _skip_evidence_check: bool,
    current_user: User,
    db: AsyncSession,
) -> Booking:
    booking = await _get_booking_or_404(booking_id, db)
    _assert_current_user_booking(booking, current_user)
    if booking.status != "after_photos_complete":
        report = await _get_damage_report(booking_id, db)
        _assert_evidence(report, "post_rental")
    return await _advance_and_flush(booking, "after_photos_complete", db)


async def mark_return_locker_opened(
    booking_id: str, current_user: User, db: AsyncSession
) -> Booking:
    booking = await _get_booking_or_404(booking_id, db)
    _assert_current_user_booking(booking, current_user)
    return await _advance_and_flush(booking, "return_locker_opened", db)


async def complete_return_video(
    booking_id: str,
    _skip_evidence_check: bool,
    current_user: User,
    db: AsyncSession,
) -> Booking:
    booking = await _get_booking_or_404(booking_id, db)
    _assert_current_user_booking(booking, current_user)
    if booking.status != "return_video_complete":
        report = await _get_damage_report(booking_id, db)
        _assert_evidence(report, "return_video")
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

    # Defensive cleanup: this method does not know which physical locker
    # (if any) the drone was actually dropped back into — that only becomes
    # known from a real future PackageDeposited webhook, same as first-time
    # intake. So never set LockerUnit.current_drone_id here. Just make sure
    # no LockerUnit is left stale, claiming this drone as "currently
    # deposited" when it has just been returned outside of that flow (e.g.
    # a drone picked up before the PackagePickedUp fix shipped).
    if booking.drone_id:
        stale_units = await db.execute(
            select(LockerUnit).where(LockerUnit.current_drone_id == booking.drone_id)
        )
        for stale_unit in stale_units.scalars().all():
            stale_unit.current_drone_id = None
            stale_unit.current_passcode = None
            db.add(stale_unit)

    await db.flush()
    logger.info("Booking returned: %s", booking_id)
    return booking
