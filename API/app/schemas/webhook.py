"""
app/schemas/webhook.py
-----------------------
Pydantic v2 request/response schemas for the Smiota webhook endpoint.
"""

from typing import Optional

from pydantic import BaseModel, Field


class SmiotaWebhookRequest(BaseModel):
    notification_type: str = Field(..., description="PackageDeposited | PackagePickedUp")
    objectId: str = Field(..., description="Smiota object ID linking to a booking")
    lockerName: Optional[str] = None
    passcode: Optional[str] = None
    courierCode: Optional[str] = None


class SmiotaWebhookResponse(BaseModel):
    status: str
    message: str
    booking_id: Optional[str] = None
