"""
app/api/routers/bookings.py
----------------------------
Booking lifecycle endpoints:
  POST  /api/bookings
  GET   /api/bookings
  GET   /api/bookings/{id}
  GET   /api/bookings/{id}/passcode
  PATCH /api/bookings/{id}/cancel
  PATCH /api/bookings/{id}/status          (admin)
  PATCH /api/bookings/{id}/smiota-link     (admin)

Damage / return endpoints:
  POST  /api/bookings/{id}/images/pre-rental
  POST  /api/bookings/{id}/images/post-rental
  GET   /api/bookings/{id}/images
  POST  /api/bookings/{id}/return

Admin condition review:
  PATCH /api/admin/drones/{id}/condition   (defined in admin.py — imported here for proximity)
"""

from typing import List

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.booking import (
    BookingCreateRequest,
    BookingListResponse,
    BookingResponse,
    BookingReturnRequest,
    BookingSmiotaLinkRequest,
    BookingStatusRequest,
    PasscodeResponse,
)
from app.schemas.damage import BookingImagesResponse, ImageUploadResponse
from app.services import booking_service, damage_service

router = APIRouter(prefix="/bookings", tags=["Bookings"])


# --------------------------------------------------------------------------- #
# Core booking CRUD
# --------------------------------------------------------------------------- #

@router.post(
    "",
    response_model=BookingResponse,
    status_code=201,
    summary="Create a new drone booking",
)
async def create_booking(
    body: BookingCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = await booking_service.create_booking(body, current_user, db)
    return BookingResponse.model_validate(booking)


@router.get(
    "",
    response_model=BookingListResponse,
    summary="List bookings (users see own; admins see all)",
)
async def list_bookings(
    status: str | None = Query(
        None, pattern="^(pending|active|completed|cancelled)$"
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await booking_service.list_bookings(
        current_user, db, status_filter=status, skip=skip, limit=limit
    )


@router.get(
    "/{booking_id}",
    response_model=BookingResponse,
    summary="Get a single booking by ID",
)
async def get_booking(
    booking_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = await booking_service.get_booking(booking_id, current_user, db)
    return BookingResponse.model_validate(booking)


@router.get(
    "/{booking_id}/passcode",
    response_model=PasscodeResponse,
    summary="Get the Smiota locker passcode for a booking",
)
async def get_passcode(
    booking_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await booking_service.get_passcode(booking_id, current_user, db)


@router.patch(
    "/{booking_id}/cancel",
    response_model=BookingResponse,
    summary="Cancel a booking",
)
async def cancel_booking(
    booking_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = await booking_service.cancel_booking(booking_id, current_user, db)
    return BookingResponse.model_validate(booking)


@router.patch(
    "/{booking_id}/status",
    response_model=BookingResponse,
    summary="Manually update a booking status — admin only",
)
async def update_booking_status(
    booking_id: str,
    body: BookingStatusRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    booking = await booking_service.update_booking_status(booking_id, body.status, db)
    return BookingResponse.model_validate(booking)


@router.patch(
    "/{booking_id}/smiota-link",
    response_model=BookingResponse,
    summary="Link a Smiota object ID to a booking — admin only",
)
async def link_smiota(
    booking_id: str,
    body: BookingSmiotaLinkRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    booking = await booking_service.link_smiota_object(booking_id, body.smiota_object_id, db)
    return BookingResponse.model_validate(booking)


# --------------------------------------------------------------------------- #
# Damage / image upload endpoints
# --------------------------------------------------------------------------- #

@router.post(
    "/{booking_id}/images/pre-rental",
    response_model=ImageUploadResponse,
    summary="Upload pre-rental drone condition images",
)
async def upload_pre_rental_images(
    booking_id: str,
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await damage_service.upload_pre_rental_images(booking_id, files, current_user, db)


@router.post(
    "/{booking_id}/images/post-rental",
    response_model=ImageUploadResponse,
    summary="Upload post-rental drone condition images",
)
async def upload_post_rental_images(
    booking_id: str,
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await damage_service.upload_post_rental_images(booking_id, files, current_user, db)


@router.get(
    "/{booking_id}/images",
    response_model=BookingImagesResponse,
    summary="Get all pre and post-rental images for a booking",
)
async def get_booking_images(
    booking_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await damage_service.get_booking_images(booking_id, current_user, db)


@router.post(
    "/{booking_id}/return",
    response_model=BookingResponse,
    summary="Return a drone and complete the booking",
)
async def return_drone(
    booking_id: str,
    body: BookingReturnRequest = BookingReturnRequest(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = await booking_service.return_drone(booking_id, body.notes, current_user, db)
    return BookingResponse.model_validate(booking)
