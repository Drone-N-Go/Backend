"""
app/api/routers/webhooks.py
----------------------------
Smiota webhook endpoint:
  POST /api/webhooks/smiota
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.webhook import SmiotaWebhookRequest, SmiotaWebhookResponse
from app.services.webhook_service import process_smiota_webhook, verify_smiota_auth

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.post(
    "/smiota",
    response_model=SmiotaWebhookResponse,
    summary="Receive Smiota locker event notifications",
    description=(
        "Called by Smiota when a drone is deposited into or picked up from a locker. "
        "Secured via HTTP Basic Auth — use your SMIOTA_API_KEY as the username, empty password."
    ),
)
async def smiota_webhook(
    body: SmiotaWebhookRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    verify_smiota_auth(request)
    return await process_smiota_webhook(body, db)
