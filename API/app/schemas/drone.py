"""
app/schemas/drone.py
---------------------
Pydantic v2 request/response schemas for drone-related endpoints.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

class DroneCreateRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_name: str = Field(..., min_length=1, max_length=255)
    subtitle: str = ""
    description: str = ""
    category: str = "professional"
    skill_level: str = "intermediate"
    serial_number: str = Field(..., min_length=1, max_length=255)
    assigned_locker_location_id: Optional[str] = None
    hourly_rate: Decimal = Field(..., gt=0)
    daily_rate: Decimal = Field(..., gt=0)
    rating: Decimal = Field(default=0, ge=0, le=5)
    review_count: int = Field(default=0, ge=0)
    image_urls: list[str] = []
    standout_features: list[str] = []
    included_items: list[str] = []
    rules: list[str] = []
    specs: dict[str, Any] = {}


class DroneUpdateRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_name: Optional[str] = Field(None, min_length=1, max_length=255)
    subtitle: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    skill_level: Optional[str] = None
    serial_number: Optional[str] = Field(None, min_length=1, max_length=255)
    assigned_locker_location_id: Optional[str] = None
    hourly_rate: Optional[Decimal] = Field(None, gt=0)
    daily_rate: Optional[Decimal] = Field(None, gt=0)
    rating: Optional[Decimal] = Field(None, ge=0, le=5)
    review_count: Optional[int] = Field(None, ge=0)
    image_urls: Optional[list[str]] = None
    standout_features: Optional[list[str]] = None
    included_items: Optional[list[str]] = None
    rules: Optional[list[str]] = None
    specs: Optional[dict[str, Any]] = None


class AssignedLocationSummary(BaseModel):
    id: str
    campus_name: str
    address: str
    latitude: float
    longitude: float
    building_name: Optional[str]


class DroneStatusRequest(BaseModel):
    status: str = Field(..., pattern="^(available|rented|damaged|maintenance)$")


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------

class DroneResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: str
    model_name: str
    subtitle: str
    description: str
    category: str
    skill_level: str
    serial_number: str
    status: str
    assigned_locker_location_id: Optional[str]
    hourly_rate: Decimal
    daily_rate: Decimal
    rating: Decimal
    review_count: int
    image_urls: list[str]
    standout_features: list[str]
    included_items: list[str]
    rules: list[str]
    specs: dict[str, Any]
    is_favorite: bool = False
    assigned_location: Optional[AssignedLocationSummary] = None
    created_at: datetime
    updated_at: datetime


class DroneListResponse(BaseModel):
    items: list[DroneResponse]
    total: int
    skip: int
    limit: int
