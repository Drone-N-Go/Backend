"""
app/api/routers/admin.py
-------------------------
Admin-only endpoints:
  GET   /api/admin/analytics
  PATCH /api/admin/drones/{drone_id}/condition
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.analytics import AnalyticsResponse
from app.schemas.damage import ConditionUpdateRequest, DamageReportResponse
from app.services.analytics_service import get_analytics
from app.services.damage_service import admin_update_condition

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get(
    "/analytics",
    response_model=AnalyticsResponse,
    summary="Get business analytics dashboard — admin only",
)
async def analytics(
    days: int = Query(30, ge=1, le=365, description="Lookback period in days"),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    return await get_analytics(days, db)


@router.patch(
    "/drones/{drone_id}/condition",
    summary="Review and update drone condition after return — admin only",
)
async def update_drone_condition(
    drone_id: str,
    body: ConditionUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    return await admin_update_condition(drone_id, body.condition_status, body.admin_notes, db)
