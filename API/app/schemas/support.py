"""
app/schemas/support.py
------------------------
Pydantic v2 request/response schemas for freeform support/damage reports.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SupportReportResponse(BaseModel):
    id: str
    user_id: str
    booking_id: str
    description: str
    image_urls: list[str]
    status: str
    admin_notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
