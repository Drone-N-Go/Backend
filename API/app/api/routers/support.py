"""
app/api/routers/support.py
-----------------------------
Freeform support/issue report endpoints:
  POST /api/support/reports
"""

from typing import List

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.support import SupportReportResponse
from app.services import support_service

router = APIRouter(prefix="/support", tags=["Support"])


@router.post(
    "/reports",
    response_model=SupportReportResponse,
    status_code=201,
    summary="Submit a freeform issue/damage report for a booking",
)
async def create_report(
    booking_id: str = Form(...),
    description: str = Form(..., min_length=1, max_length=4000),
    files: List[UploadFile] = File(default=[]),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    report = await support_service.create_support_report(
        booking_id, description, files, current_user, db
    )
    return SupportReportResponse.model_validate(report)
