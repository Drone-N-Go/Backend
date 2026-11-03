"""
app/services/webhook_service.py
--------------------------------
Business logic for processing Smiota locker webhook events.
"""

import logging
from datetime import datetime, timezone

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.booking_lifecycle import TERMINAL_BOOKING_STATUSES
from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.models.booking import Booking
from app.models.drone import Drone
from app.models.locker_unit import LockerUnit
from app.models.smiota_event import SmiotaEvent
from app.schemas.webhook import SmiotaWebhookRequest, SmiotaWebhookResponse

import base64
import hmac as _hmac

logger = logging.getLogger(__name__)
settings = get_settings()


# --------------------------------------------------------------------------- #
# Basic Auth verification
# --------------------------------------------------------------------------- #

def verify_smiota_auth(request: Request) -> None:
    """
    Verify HTTP Basic Auth for the Smiota webhook endpoint.
    Convention: API key in the username position, empty password.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Basic "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header.",
            headers={"WWW-Authenticate": "Basic"},
        )

    try:
        decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
        api_key, password = decoded.split(":", maxsplit=1)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed Basic Auth credentials.",
        )

    if password != "":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Basic Auth password.",
        )

    try:
        expected_api_key = settings.require_smiota_api_key()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )

    # Use constant-time comparison to prevent timing attacks on the API key.
    if not _hmac.compare_digest(api_key, expected_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
        )


# --------------------------------------------------------------------------- #
# Resolving which cabinet and which booking an event belongs to
# --------------------------------------------------------------------------- #
#
# Smiota's `objectId` is whatever label the depositor typed (in practice the
# drone's model name, e.g. "Mavic Pro"), so it is NOT unique: every rental of
# a drone, and every drone of the same model, can carry the same one. Matching
# events to bookings by objectId alone used to raise MultipleResultsFound (a
# 500) once a drone had been rented twice, or attach an event to an old,
# finished booking. (Fixed 2026-11-02.)
#
# Events are now resolved in this order:
#   1. The cabinet, by `lockerName` (LockerUnit.smiota_locker_name).
#   2. The booking, as the ACTIVE booking for the drone linked to that cabinet.
#   3. Only when the cabinet can't be resolved (no or unknown lockerName):
#      the ACTIVE booking carrying this objectId, and only if exactly one does.
# Finished bookings (returned / cancelled / no_show) are never matched, so a
# stale objectId left on them is harmless.

# Bookings that are not rentals yet or anymore. pending_payment is an unpaid
# checkout hold: it must not receive a passcode until Stripe confirms payment
# (payment_service.activate_paid_booking reads it off the cabinet then).
_NOT_ACTIVE_STATUSES = set(TERMINAL_BOOKING_STATUSES) | {"pending_payment"}

# A deposit only fulfils a booking that is still waiting for its drone.
_AWAITING_PICKUP_STATUSES = ("reserved", "ready_for_pickup")


async def _resolve_unit(body: SmiotaWebhookRequest, db: AsyncSession) -> LockerUnit | None:
    if not body.lockerName:
        return None
    result = await db.execute(
        select(LockerUnit).where(LockerUnit.smiota_locker_name == body.lockerName)
    )
    units = result.scalars().all()
    if len(units) > 1:
        logger.warning(
            "Smiota lockerName %s is mapped to %d cabinets; cannot tell them apart.",
            body.lockerName,
            len(units),
        )
        return None
    return units[0] if units else None


async def _active_booking_for_drone(
    drone_id: str, db: AsyncSession, statuses: tuple[str, ...] | None = None
) -> Booking | None:
    query = select(Booking).where(
        Booking.drone_id == drone_id,
        Booking.status.notin_(_NOT_ACTIVE_STATUSES),
    )
    if statuses:
        query = query.where(Booking.status.in_(statuses))
    result = await db.execute(query.order_by(Booking.created_at.desc()).limit(1))
    return result.scalars().first()


async def _drone_has_open_booking(drone_id: str, db: AsyncSession) -> bool:
    """Any booking still holding this drone, including an unpaid checkout."""
    result = await db.execute(
        select(Booking.id)
        .where(
            Booking.drone_id == drone_id,
            Booking.status.notin_(TERMINAL_BOOKING_STATUSES),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _resolve_booking(
    body: SmiotaWebhookRequest,
    unit: LockerUnit | None,
    db: AsyncSession,
    statuses: tuple[str, ...] | None = None,
) -> Booking | None:
    if unit is not None:
        # The cabinet is known: only its own drone's booking can match. Never
        # fall back to objectId here, or a same-named drone in another locker
        # could be handed this cabinet's passcode.
        if not unit.current_drone_id:
            return None
        return await _active_booking_for_drone(unit.current_drone_id, db, statuses)

    query = select(Booking).where(
        Booking.smiota_object_id == body.objectId,
        Booking.status.notin_(_NOT_ACTIVE_STATUSES),
    )
    if statuses:
        query = query.where(Booking.status.in_(statuses))
    matches = (await db.execute(query.limit(2))).scalars().all()
    if len(matches) > 1:
        logger.warning(
            "Smiota objectId %s matches more than one active booking and no lockerName "
            "identifies the cabinet; leaving the event unmatched.",
            body.objectId,
        )
        return None
    return matches[0] if matches else None


async def _unit_for_drone(drone_id: str, db: AsyncSession) -> LockerUnit | None:
    result = await db.execute(select(LockerUnit).where(LockerUnit.current_drone_id == drone_id))
    return result.scalar_one_or_none()


def _hold_deposit_on_unit(unit: LockerUnit, body: SmiotaWebhookRequest) -> None:
    """Record the deposit currently sitting in this cabinet. The objectId and
    courier code describe THIS deposit only; they are cleared when it is
    picked up (see _clear_deposit_from_unit) and replaced by the next one."""
    unit.current_passcode = body.passcode
    unit.smiota_metadata = {
        **(unit.smiota_metadata or {}),
        "pending_deposit_object_id": body.objectId,
        "pending_deposit_courier_code": body.courierCode,
    }


def _clear_deposit_from_unit(unit: LockerUnit) -> None:
    """The deposit has been taken out: forget its passcode and Smiota ids.
    The cabinet keeps its drone link (current_drone_id) — only an admin
    unlinks a drone from its cabinet."""
    unit.current_passcode = None
    metadata = dict(unit.smiota_metadata or {})
    metadata.pop("pending_deposit_object_id", None)
    metadata.pop("pending_deposit_courier_code", None)
    unit.smiota_metadata = metadata


async def _record(event: SmiotaEvent, db: AsyncSession, status_value: str, error: str | None = None) -> None:
    event.processed = status_value in {"processed", "ignored"}
    event.processing_status = status_value
    event.error_message = error
    db.add(event)
    await db.flush()


# --------------------------------------------------------------------------- #
# Restock handling (PackageDeposited not fulfilling a waiting booking)
# --------------------------------------------------------------------------- #

async def _handle_restock_deposit(
    body: SmiotaWebhookRequest, unit: LockerUnit | None, event: SmiotaEvent, db: AsyncSession
) -> SmiotaWebhookResponse:
    """
    A drone went into a cabinet and no booking is waiting for it. This is
    either staff stocking the locker or a renter dropping the drone back off
    at the end of a rental. Either way the cabinet now holds this deposit:
    keep its passcode and Smiota ids on the cabinet so the next booking of
    the cabinet's drone picks them up (create_booking / activate_paid_booking).

    The cabinet's drone is marked available here only when nothing is still
    holding it. A drone deposited mid-return stays `rented` until the renter
    completes the return (booking_service.complete_return frees it), so it
    can't be booked by someone else while the return is still in progress.
    """
    if unit is None:
        reason = (
            f"No locker unit found for lockerName '{body.lockerName}'."
            if body.lockerName
            else "No matching booking and no lockerName to resolve a restock target."
        )
        logger.warning(
            "PackageDeposited could not be matched to a cabinet. locker_name=%s object_id=%s",
            body.lockerName,
            body.objectId,
        )
        await _record(event, db, "unmatched", reason)
        return SmiotaWebhookResponse(status="received", message=f"{reason} Event recorded only.")

    _hold_deposit_on_unit(unit, body)
    db.add(unit)

    drone = None
    if unit.current_drone_id:
        drone_result = await db.execute(select(Drone).where(Drone.id == unit.current_drone_id))
        drone = drone_result.scalar_one_or_none()

    message = "Deposit recorded; no drone assigned to this locker yet."
    if drone is None:
        logger.warning(
            "PackageDeposited — locker %s (name=%s) has no drone assigned; passcode stored only.",
            unit.id,
            body.lockerName,
        )
    elif drone.status == "damaged":
        message = "Deposit recorded; drone is marked damaged and stays unavailable."
        logger.warning("PackageDeposited for damaged drone %s in locker %s — left damaged.", drone.id, unit.id)
    elif await _drone_has_open_booking(drone.id, db):
        message = "Deposit recorded; drone stays held until its current booking finishes."
        logger.info(
            "PackageDeposited — drone %s back in locker %s; booking still open, status left as %s.",
            drone.id,
            unit.id,
            drone.status,
        )
    else:
        drone.status = "available"
        db.add(drone)
        message = "Restock deposit processed; drone marked available."
        logger.info("PackageDeposited — drone %s marked available (locker %s)", drone.id, unit.id)

    await _record(event, db, "processed")
    return SmiotaWebhookResponse(status="processed", message=message)


# --------------------------------------------------------------------------- #
# Webhook processing
# --------------------------------------------------------------------------- #

async def process_smiota_webhook(
    body: SmiotaWebhookRequest, db: AsyncSession
) -> SmiotaWebhookResponse:
    """
    Process an incoming Smiota webhook event.

      - PackageDeposited : A drone went into a cabinet.
          * If the cabinet's drone has a booking waiting for pickup, the
            passcode goes on that booking and it becomes ready_for_pickup.
          * Otherwise (staff restock, or a renter's return drop-off) the
            deposit is held on the cabinet for the next booking; see
            _handle_restock_deposit.
      - PackagePickedUp  : The drone was taken out. Audit only for the
          booking (the app still drives locker-opened, QR verification,
          photos and start-use); the cabinet's passcode and deposit ids are
          cleared. The drone STAYS linked to its cabinet.
    """

    # 1. Log raw event to smiota_events table
    event = SmiotaEvent(
        notification_type=body.notification_type,
        object_id=body.objectId,
        locker_name=body.lockerName,
        passcode=body.passcode,
        courier_code=body.courierCode,
        tracking_id=body.trackingID,
        raw_payload=body.model_dump(),
        processed=False,
        processing_status="received",
    )
    db.add(event)
    await db.flush()
    logger.info(
        "Smiota webhook audit row created | event_id=%s type=%s object_id=%s status=%s",
        event.id,
        event.notification_type,
        event.object_id,
        event.processing_status,
    )

    unit = await _resolve_unit(body, db)

    # 2. PackageDeposited
    if body.notification_type == "PackageDeposited":
        booking = await _resolve_booking(body, unit, db, statuses=_AWAITING_PICKUP_STATUSES)
        if booking is None:
            return await _handle_restock_deposit(body, unit, event, db)

        if booking.status == "ready_for_pickup" and booking.smiota_passcode:
            logger.info("Duplicate PackageDeposited ignored for booking %s", booking.id)
            await _record(event, db, "ignored", "Duplicate deposit event ignored.")
            return SmiotaWebhookResponse(
                status="received",
                message="Duplicate deposit event ignored.",
                booking_id=booking.id,
            )

        # Store locker access details on the booking (consumer app reads from here).
        booking.smiota_passcode = body.passcode
        booking.smiota_locker_name = body.lockerName
        booking.smiota_courier_code = body.courierCode
        booking.smiota_object_id = body.objectId
        if booking.status == "reserved":
            booking.status = "ready_for_pickup"
            booking.ready_for_pickup_at = datetime.now(timezone.utc)
        db.add(booking)

        # Also hold the deposit on the cabinet so admins can reveal it.
        target_unit = unit or (await _unit_for_drone(booking.drone_id, db) if booking.drone_id else None)
        if target_unit is not None:
            _hold_deposit_on_unit(target_unit, body)
            db.add(target_unit)
        else:
            logger.warning("PackageDeposited — no locker unit found for drone_id %s", booking.drone_id)

        logger.info("PackageDeposited — booking %s ready for pickup | locker: %s", booking.id, body.lockerName)
        await _record(event, db, "processed")
        return SmiotaWebhookResponse(
            status="processed",
            message="Event 'PackageDeposited' handled successfully.",
            booking_id=booking.id,
        )

    # 3. PackagePickedUp
    if body.notification_type == "PackagePickedUp":
        booking = await _resolve_booking(body, unit, db)
        if booking is None:
            logger.warning(
                "PackagePickedUp with no active booking | locker_name=%s object_id=%s",
                body.lockerName,
                body.objectId,
            )
            await _record(event, db, "unmatched", "No active booking found for this pickup.")
            return SmiotaWebhookResponse(
                status="received",
                message="No active booking found for this pickup.",
            )

        drone_result = await db.execute(select(Drone).where(Drone.id == booking.drone_id))
        drone = drone_result.scalar_one_or_none()
        if drone:
            drone.status = "rented"
            db.add(drone)

        # The drone is out of the cabinet: clear that deposit's passcode and
        # ids, but keep the cabinet's link to its drone. The drone comes back
        # to this cabinet on return; only an admin unlinks it.
        target_unit = unit or (await _unit_for_drone(booking.drone_id, db) if booking.drone_id else None)
        if target_unit is not None:
            _clear_deposit_from_unit(target_unit)
            db.add(target_unit)

        logger.info("PackagePickedUp — booking %s audited | drone %s rented", booking.id, booking.drone_id)
        await _record(event, db, "processed")
        return SmiotaWebhookResponse(
            status="processed",
            message="Event 'PackagePickedUp' handled successfully.",
            booking_id=booking.id,
        )

    # 4. Anything else
    logger.warning("Unrecognized Smiota notification_type: %s", body.notification_type)
    await _record(event, db, "failed", f"Unrecognized notification_type: {body.notification_type}")
    return SmiotaWebhookResponse(
        status="failed",
        message=f"Unrecognized notification_type: {body.notification_type}",
    )


async def record_smiota_webhook_failure(
    raw_payload: dict | None,
    *,
    status_value: str,
    error_message: str,
) -> None:
    """
    Persist webhook attempts that fail before normal business processing.

    This uses an independent session so a 401/422 response from the webhook
    request cannot roll back the audit trail.
    """
    payload = raw_payload or {}

    def optional_str(value):
        return None if value is None else str(value)

    event = SmiotaEvent(
        notification_type=str(payload.get("notification_type") or "InvalidWebhook"),
        object_id=str(payload.get("objectId") or payload.get("object_id") or "unknown"),
        locker_name=optional_str(payload.get("lockerName") or payload.get("locker_name")),
        passcode=optional_str(payload.get("passcode")),
        courier_code=optional_str(payload.get("courierCode") or payload.get("courier_code")),
        tracking_id=optional_str(payload.get("trackingID") or payload.get("tracking_id")),
        raw_payload=payload,
        processed=False,
        processing_status=status_value,
        error_message=error_message[:500],
    )
    async with AsyncSessionLocal() as audit_db:
        audit_db.add(event)
        await audit_db.commit()
    logger.info(
        "Smiota webhook failure audited | type=%s object_id=%s status=%s error=%s",
        event.notification_type,
        event.object_id,
        event.processing_status,
        event.error_message,
    )
