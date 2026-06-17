"""
app/api/routers/bookings.py
----------------------------
Booking lifecycle endpoints:
  POST  /api/bookings
  GET   /api/bookings
  GET   /api/bookings/{id}
  GET   /api/bookings/{id}/passcode
  PATCH /api/bookings/{id}/cancel

Damage / return endpoints:
  POST  /api/bookings/{id}/images/pre-rental
  POST  /api/bookings/{id}/images/post-rental
  POST  /api/bookings/{id}/return-video
  GET   /api/bookings/{id}/images
  POST  /api/bookings/{id}/locker-opened
  POST  /api/bookings/{id}/case-verified
  POST  /api/bookings/{id}/before-photos/complete
  POST  /api/bookings/{id}/start-use
  POST  /api/bookings/{id}/return/start
  POST  /api/bookings/{id}/after-photos/complete
  POST  /api/bookings/{id}/return-locker-opened
  POST  /api/bookings/{id}/return-video/complete
  POST  /api/bookings/{id}/complete-return

"""

from typing import List

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.booking import (
    BookingCreateRequest,
    BookingReturnRequest,
    CaseQRVerificationRequest,
    EvidenceCompletionRequest,
    BookingListResponse,
    BookingResponse,
    PasscodeResponse,
)
from app.core.booking_lifecycle import BOOKING_STATUS_PATTERN
from app.schemas.damage import BookingImagesResponse, ImageUploadResponse, ReturnVideoUploadResponse
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
    return await booking_service.get_booking_detail(booking.id, current_user, db)


@router.get(
    "",
    response_model=BookingListResponse,
    summary="List the current user's bookings",
)
async def list_bookings(
    status: str | None = Query(
        None, pattern=BOOKING_STATUS_PATTERN
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
    "/active",
    response_model=BookingResponse | None,
    summary="Get the current user's active booking",
)
async def get_active_booking(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await booking_service.get_active_booking(current_user, db)


@router.get(
    "/history",
    response_model=BookingListResponse,
    summary="Get the current user's returned and cancelled bookings",
)
async def get_booking_history(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await booking_service.list_booking_history(current_user, db, skip=skip, limit=limit)


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
    return await booking_service.get_booking_detail(booking_id, current_user, db)


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
    return await booking_service.get_booking_detail(booking.id, current_user, db)


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


@router.post(
    "/{booking_id}/return-video",
    response_model=ReturnVideoUploadResponse,
    summary="Upload required return video",
)
async def upload_return_video(
    booking_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await damage_service.upload_return_video(booking_id, file, current_user, db)


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


# --------------------------------------------------------------------------- #
# Frontend-aligned lifecycle endpoints
# --------------------------------------------------------------------------- #

@router.post(
    "/{booking_id}/locker-opened",
    response_model=BookingResponse,
    summary="Mark pickup locker opened",
)
async def mark_locker_opened(
    booking_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = await booking_service.mark_locker_opened(booking_id, current_user, db)
    return await booking_service.get_booking_detail(booking.id, current_user, db)


@router.post(
    "/{booking_id}/case-verified",
    response_model=BookingResponse,
    summary="Mark pickup case QR verified",
)
async def mark_case_verified(
    booking_id: str,
    body: CaseQRVerificationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = await booking_service.mark_case_verified(booking_id, body.qr_payload, current_user, db)
    return await booking_service.get_booking_detail(booking.id, current_user, db)


@router.post(
    "/{booking_id}/before-photos/complete",
    response_model=BookingResponse,
    summary="Complete before-rental photo documentation",
)
async def complete_before_photos(
    booking_id: str,
    body: EvidenceCompletionRequest = EvidenceCompletionRequest(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = await booking_service.complete_before_photos(
        booking_id, False, current_user, db
    )
    return await booking_service.get_booking_detail(booking.id, current_user, db)


@router.post(
    "/{booking_id}/start-use",
    response_model=BookingResponse,
    summary="Move booking into active in-use state",
)
async def start_use(
    booking_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = await booking_service.start_use(booking_id, current_user, db)
    return await booking_service.get_booking_detail(booking.id, current_user, db)


@router.post(
    "/{booking_id}/return/start",
    response_model=BookingResponse,
    summary="Start return flow",
)
async def start_return(
    booking_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = await booking_service.start_return(booking_id, current_user, db)
    return await booking_service.get_booking_detail(booking.id, current_user, db)


@router.post(
    "/{booking_id}/return/case-verified",
    response_model=BookingResponse,
    summary="Verify return case QR and start return flow",
)
async def mark_return_case_verified(
    booking_id: str,
    body: CaseQRVerificationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = await booking_service.mark_return_case_verified(booking_id, body.qr_payload, current_user, db)
    return await booking_service.get_booking_detail(booking.id, current_user, db)


@router.post(
    "/{booking_id}/after-photos/complete",
    response_model=BookingResponse,
    summary="Complete after-rental photo documentation",
)
async def complete_after_photos(
    booking_id: str,
    body: EvidenceCompletionRequest = EvidenceCompletionRequest(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = await booking_service.complete_after_photos(
        booking_id, False, current_user, db
    )
    return await booking_service.get_booking_detail(booking.id, current_user, db)


@router.post(
    "/{booking_id}/return-locker-opened",
    response_model=BookingResponse,
    summary="Mark return locker opened",
)
async def mark_return_locker_opened(
    booking_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = await booking_service.mark_return_locker_opened(booking_id, current_user, db)
    return await booking_service.get_booking_detail(booking.id, current_user, db)


@router.post(
    "/{booking_id}/return-video/complete",
    response_model=BookingResponse,
    summary="Complete return video documentation",
)
async def complete_return_video(
    booking_id: str,
    body: EvidenceCompletionRequest = EvidenceCompletionRequest(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = await booking_service.complete_return_video(
        booking_id, False, current_user, db
    )
    return await booking_service.get_booking_detail(booking.id, current_user, db)


@router.post(
    "/{booking_id}/complete-return",
    response_model=BookingResponse,
    summary="Complete the booking return",
)
async def complete_return(
    booking_id: str,
    body: BookingReturnRequest = BookingReturnRequest(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = await booking_service.complete_return(booking_id, body.notes, current_user, db)
    return await booking_service.get_booking_detail(booking.id, current_user, db)
