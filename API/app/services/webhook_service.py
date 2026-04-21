"""
app/services/webhook_service.py
--------------------------------
Business logic for processing Smiota locker webhook events.

Console output conventions (visible during development/testing):
  ***CHECKOUT TOKEN*** : <passcode>   — when a drone is deposited (PackageDeposited)
  ***RETURNING TOKEN*** : <passcode>  — when a drone is picked up for return (PackagePickedUp)
"""

import logging

from fastapi import HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.booking import Booking
from app.models.drone import Drone
from app.models.smiota_event import SmiotaEvent
from app.schemas.webhook import SmiotaWebhookRequest, SmiotaWebhookResponse

import base64

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
        api_key, *_ = decoded.split(":", maxsplit=1)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed Basic Auth credentials.",
        )

    if api_key != settings.smiota_api_key:
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
      - PackageDeposited : Drone placed in locker → store passcode on booking
      - PackagePickedUp  : User picked up drone → mark booking active
    """

    # 1. Log raw event to smiota_events table
    event = SmiotaEvent(
        notification_type=body.notification_type,
        object_id=body.objectId,
        locker_name=body.lockerName,
        passcode=body.passcode,
        courier_code=body.courierCode,
        raw_payload=body.model_dump(),
        processed=False,
    )
    db.add(event)
    await db.flush()

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
        return SmiotaWebhookResponse(
            status="received",
            message="No matching booking found for this Smiota object ID.",
        )

    # 3. Handle event types
    if body.notification_type == "PackageDeposited":
        # Store locker access details on the booking
        booking.smiota_passcode = body.passcode
        booking.smiota_locker_name = body.lockerName
        booking.smiota_courier_code = body.courierCode
        db.add(booking)

        # ------------------------------------------------------------------ #
        # DEVELOPER CONSOLE OUTPUT — Checkout token visibility
        # ------------------------------------------------------------------ #
        print(f"\n{'='*60}")
        print(f"  ***CHECKOUT TOKEN*** : {body.passcode}")
        print(f"  Booking ID          : {booking.id}")
        print(f"  Locker Name         : {body.lockerName}")
        print(f"  Courier Code        : {body.courierCode}")
        print(f"  Object ID           : {body.objectId}")
        print(f"{'='*60}\n")

        logger.info(
            "PackageDeposited — booking %s | passcode: %s | locker: %s",
            booking.id,
            body.passcode,
            body.lockerName,
        )

    elif body.notification_type == "PackagePickedUp":
        # User picked up the drone → activate the booking
        booking.status = "active"
        db.add(booking)

        # Also ensure drone is marked rented
        drone_result = await db.execute(select(Drone).where(Drone.id == booking.drone_id))
        drone = drone_result.scalar_one_or_none()
        if drone:
            drone.status = "rented"
            db.add(drone)

        # ------------------------------------------------------------------ #
        # DEVELOPER CONSOLE OUTPUT — Returning token visibility
        # ------------------------------------------------------------------ #
        print(f"\n{'='*60}")
        print(f"  ***RETURNING TOKEN*** : {body.passcode}")
        print(f"  Booking ID           : {booking.id}")
        print(f"  Locker Name          : {body.lockerName}")
        print(f"  Object ID            : {body.objectId}")
        print(f"{'='*60}\n")

        logger.info(
            "PackagePickedUp — booking %s activated | drone %s → rented",
            booking.id,
            booking.drone_id,
        )

    else:
        logger.warning("Unrecognized Smiota notification_type: %s", body.notification_type)

    # 4. Mark event as processed
    event.processed = True
    db.add(event)
    await db.flush()

    return SmiotaWebhookResponse(
        status="processed",
        message=f"Event '{body.notification_type}' handled successfully.",
        booking_id=booking.id,
    )
