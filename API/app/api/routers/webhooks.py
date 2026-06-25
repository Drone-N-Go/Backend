"""
app/api/routers/webhooks.py
----------------------------
Smiota webhook endpoint:
  POST /api/webhooks/smiota
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.webhook import SmiotaWebhookRequest, SmiotaWebhookResponse
from app.services.webhook_service import (
    process_smiota_webhook,
    record_smiota_webhook_failure,
    verify_smiota_auth,
)

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
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    try:
        raw_payload = await request.json()
        if not isinstance(raw_payload, dict):
            raw_payload = {"payload": raw_payload}
    except Exception as exc:
        raw_payload = {"_parse_error": "Invalid JSON body."}
        await record_smiota_webhook_failure(
            raw_payload,
            db,
            status_value="failed",
            error_message=f"Invalid JSON body: {exc}",
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid JSON body.",
        )

    try:
        verify_smiota_auth(request)
    except HTTPException as exc:
        await record_smiota_webhook_failure(
            raw_payload,
            db,
            status_value="auth_failed",
            error_message=str(exc.detail),
        )
        raise

    try:
        body = SmiotaWebhookRequest.model_validate(raw_payload)
    except ValidationError as exc:
        await record_smiota_webhook_failure(
            raw_payload,
            db,
            status_value="failed",
            error_message=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(),
        )

    return await process_smiota_webhook(body, db)
