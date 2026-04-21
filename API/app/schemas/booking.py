"""
app/schemas/booking.py
-----------------------
Pydantic v2 request/response schemas for booking-related endpoints.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

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


class BookingStatusRequest(BaseModel):
    status: str = Field(..., pattern="^(pending|active|completed|cancelled)$")


class BookingSmiotaLinkRequest(BaseModel):
    smiota_object_id: str = Field(..., min_length=1)


class BookingReturnRequest(BaseModel):
    notes: Optional[str] = None


class BookingCancelRequest(BaseModel):
    pass


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
