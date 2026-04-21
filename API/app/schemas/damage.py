"""
app/schemas/damage.py
----------------------
Pydantic v2 request/response schemas for damage reports and image uploads.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

class ConditionUpdateRequest(BaseModel):
    condition_status: str = Field(..., pattern="^(undamaged|damaged|needs_review)$")
    admin_notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------

class DamageReportResponse(BaseModel):
    id: str
    booking_id: str
    user_id: str
    drone_id: str
    pre_rental_images: list[str]
    post_rental_images: list[str]
    admin_notes: Optional[str]
    condition_status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ImageUploadResponse(BaseModel):
    booking_id: str
    image_type: str   # "pre_rental" or "post_rental"
    uploaded_urls: list[str]
    damage_report: DamageReportResponse


class BookingImagesResponse(BaseModel):
    booking_id: str
    pre_rental_images: list[str]
    post_rental_images: list[str]
