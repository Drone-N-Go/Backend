"""
app/schemas/location.py
------------------------
Pydantic v2 request/response schemas for locker location and unit endpoints.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Locker Location Requests
# ---------------------------------------------------------------------------

class LocationCreateRequest(BaseModel):
    campus_name: str = Field(..., min_length=1, max_length=255)
    address: str = Field(..., min_length=1)
    latitude: float
    longitude: float
    building_name: Optional[str] = None
    landmarks: Optional[str] = None
    directions: Optional[str] = None


class LocationUpdateRequest(BaseModel):
    campus_name: Optional[str] = Field(None, min_length=1, max_length=255)
    address: Optional[str] = Field(None, min_length=1)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    building_name: Optional[str] = None
    landmarks: Optional[str] = None
    directions: Optional[str] = None


# ---------------------------------------------------------------------------
# Locker Unit Requests
# ---------------------------------------------------------------------------

class LockerUnitCreateRequest(BaseModel):
    unit_number: str = Field(..., min_length=1, max_length=50)
    status: str = Field("available", pattern="^(available|occupied|maintenance)$")


class LockerUnitUpdateRequest(BaseModel):
    unit_number: Optional[str] = Field(None, min_length=1, max_length=50)
    status: Optional[str] = Field(None, pattern="^(available|occupied|maintenance)$")


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------

class LockerUnitResponse(BaseModel):
    id: str
    location_id: str
    unit_number: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LocationResponse(BaseModel):
    id: str
    campus_name: str
    locker_hardware_id: Optional[str]
    address: str
    latitude: float
    longitude: float
    building_name: Optional[str]
    landmarks: Optional[str]
    directions: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LocationDetailResponse(LocationResponse):
    """Location with its locker units included."""
    units: list[LockerUnitResponse] = []


class LocationListResponse(BaseModel):
    items: list[LocationResponse]
    total: int
    skip: int
    limit: int


class LockerUnitListResponse(BaseModel):
    items: list[LockerUnitResponse]
    total: int
    skip: int
    limit: int
