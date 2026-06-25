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
# Webhook processing
# --------------------------------------------------------------------------- #

async def process_smiota_webhook(
    body: SmiotaWebhookRequest, db: AsyncSession
) -> SmiotaWebhookResponse:
    """
    Process an incoming Smiota webhook event.

    Supported notification_type values:
      - PackageDeposited : Drone placed in locker → store passcode and mark ready for pickup
      - PackagePickedUp  : User picked up drone → audit only; iOS drives verification states
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

    # 2. Find matching booking via smiota_object_id
    booking_result = await db.execute(
        select(Booking).where(Booking.smiota_object_id == body.objectId)
    )
    booking = booking_result.scalar_one_or_none()

    if not booking:
        logger.warning(
            "Smiota event received for unknown objectId: %s (type: %s)",
            body.objectId,
            body.notification_type,
        )
        event.processing_status = "unmatched"
        event.error_message = "No matching booking found for this Smiota object ID."
        db.add(event)
        await db.flush()
        return SmiotaWebhookResponse(
            status="received",
            message="No matching booking found for this Smiota object ID.",
        )

    # 3. Handle event types
    if body.notification_type == "PackageDeposited":
        if booking.status not in {"reserved", "ready_for_pickup"}:
            logger.warning(
                "Ignoring PackageDeposited for booking %s in status %s",
                booking.id,
                booking.status,
            )
            event.processed = True
            event.processing_status = "ignored"
            event.error_message = "Booking is no longer awaiting pickup."
            db.add(event)
            await db.flush()
            return SmiotaWebhookResponse(
                status="received",
                message="Event ignored because booking is no longer awaiting pickup.",
                booking_id=booking.id,
            )

        if booking.status == "ready_for_pickup" and booking.smiota_passcode:
            logger.info("Duplicate PackageDeposited ignored for booking %s", booking.id)
            event.processed = True
            event.processing_status = "ignored"
            event.error_message = "Duplicate deposit event ignored."
            db.add(event)
            await db.flush()
            return SmiotaWebhookResponse(
                status="received",
                message="Duplicate deposit event ignored.",
                booking_id=booking.id,
            )

        # Store locker access details on the booking (consumer app reads from here).
        booking.smiota_passcode = body.passcode
        booking.smiota_locker_name = body.lockerName
        booking.smiota_courier_code = body.courierCode
        if booking.status == "reserved":
            booking.status = "ready_for_pickup"
            booking.ready_for_pickup_at = datetime.now(timezone.utc)
        db.add(booking)

        # Also write the passcode directly onto the cabinet so admins can reveal it.
        if booking.drone_id and body.passcode:
            unit_result = await db.execute(
                select(LockerUnit).where(LockerUnit.current_drone_id == booking.drone_id)
            )
            unit = unit_result.scalar_one_or_none()
            if unit:
                unit.current_passcode = body.passcode
                db.add(unit)
                logger.info(
                    "PackageDeposited — cabinet %s passcode stored | locker: %s",
                    unit.id,
                    body.lockerName,
                )
            else:
                logger.warning(
                    "PackageDeposited — no locker unit found for drone_id %s",
                    booking.drone_id,
                )

        logger.info(
            "PackageDeposited — booking %s ready for pickup | locker: %s",
            booking.id,
            body.lockerName,
        )

    elif body.notification_type == "PackagePickedUp":
        # Audit only. The app must still confirm locker opened, QR verification,
        # before photos, and explicit start-use before reaching in_use.
        drone_result = await db.execute(select(Drone).where(Drone.id == booking.drone_id))
        drone = drone_result.scalar_one_or_none()
        if drone:
            drone.status = "rented"
            db.add(drone)

        # Clear the cabinet passcode — drone is no longer inside.
        if booking.drone_id:
            unit_result = await db.execute(
                select(LockerUnit).where(LockerUnit.current_drone_id == booking.drone_id)
            )
            unit = unit_result.scalar_one_or_none()
            if unit:
                unit.current_passcode = None
                db.add(unit)

        logger.info(
            "PackagePickedUp — booking %s audited | drone %s remains rented",
            booking.id,
            booking.drone_id,
        )

    else:
        logger.warning("Unrecognized Smiota notification_type: %s", body.notification_type)
        event.error_message = f"Unrecognized notification_type: {body.notification_type}"

    # 4. Mark event as processed
    event.processed = True
    event.processing_status = "processed" if not event.error_message else "failed"
    db.add(event)
    await db.flush()

    if event.processing_status == "failed":
        return SmiotaWebhookResponse(
            status="failed",
            message=event.error_message or f"Event '{body.notification_type}' failed.",
            booking_id=booking.id,
        )

    return SmiotaWebhookResponse(
        status="processed",
        message=f"Event '{body.notification_type}' handled successfully.",
        booking_id=booking.id,
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
