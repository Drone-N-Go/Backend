"""
app/schemas/drone.py
---------------------
Pydantic v2 request/response schemas for drone-related endpoints.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

class DroneCreateRequest(BaseModel):
    model_name: str = Field(..., min_length=1, max_length=255)
    serial_number: str = Field(..., min_length=1, max_length=255)
    assigned_locker_location_id: Optional[str] = None
    hourly_rate: Decimal = Field(..., gt=0)
    daily_rate: Decimal = Field(..., gt=0)


class DroneUpdateRequest(BaseModel):
    model_name: Optional[str] = Field(None, min_length=1, max_length=255)
    serial_number: Optional[str] = Field(None, min_length=1, max_length=255)
    assigned_locker_location_id: Optional[str] = None
    hourly_rate: Optional[Decimal] = Field(None, gt=0)
    daily_rate: Optional[Decimal] = Field(None, gt=0)


class DroneStatusRequest(BaseModel):
    status: str = Field(..., pattern="^(available|rented|damaged|maintenance)$")


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------

class DroneResponse(BaseModel):
    id: str
    model_name: str
    serial_number: str
    status: str
    assigned_locker_location_id: Optional[str]
    hourly_rate: Decimal
    daily_rate: Decimal
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DroneListResponse(BaseModel):
    items: list[DroneResponse]
    total: int
    skip: int
    limit: int
