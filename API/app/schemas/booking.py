"""
app/schemas/booking.py
-----------------------
Pydantic v2 request/response schemas for booking-related endpoints.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

class BookingCreateRequest(BaseModel):
    drone_id: str
    location_id: str
    pickup_time: str = Field(..., description="ISO 8601 datetime string")
    rental_duration: int = Field(..., gt=0)
    rental_type: str = Field(..., pattern="^(hourly|daily)$")


class BookingReturnRequest(BaseModel):
    notes: Optional[str] = None


class BookingCancelRequest(BaseModel):
    pass


class EvidenceCompletionRequest(BaseModel):
    skip_evidence_check: bool = Field(
        default=False,
        description="Development/demo override for completing a documentation step without uploaded evidence.",
    )


class CaseQRVerificationRequest(BaseModel):
    qr_payload: str = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------

class BookingResponse(BaseModel):
    id: str
    user_id: str
    drone_id: str
    location_id: str
    pickup_time: str
    rental_duration: int
    rental_type: str
    status: str
    total_cost: Decimal
    smiota_object_id: Optional[str]
    smiota_passcode: Optional[str]
    smiota_locker_name: Optional[str]
    smiota_courier_code: Optional[str]
    ready_for_pickup_at: Optional[datetime]
    locker_opened_at: Optional[datetime]
    case_verified_at: Optional[datetime]
    before_photos_completed_at: Optional[datetime]
    in_use_at: Optional[datetime]
    return_started_at: Optional[datetime]
    after_photos_completed_at: Optional[datetime]
    return_locker_opened_at: Optional[datetime]
    return_video_completed_at: Optional[datetime]
    returned_at: Optional[datetime]
    cancelled_at: Optional[datetime]
    drone: Optional[dict[str, Any]] = None
    location: Optional[dict[str, Any]] = None
    pre_rental_images: list[str] = []
    post_rental_images: list[str] = []
    return_video_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PasscodeResponse(BaseModel):
    booking_id: str
    passcode: str
    locker_name: Optional[str]
    courier_code: Optional[str]


class BookingListResponse(BaseModel):
    items: list[BookingResponse]
    total: int
    skip: int
    limit: int
