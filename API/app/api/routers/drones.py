"""
app/api/routers/drones.py
--------------------------
Drone management endpoints:
  GET    /api/drones                        (public)
  GET    /api/drones/{drone_id}             (public)
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_optional_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.drone import DroneListResponse, DroneResponse
from app.services import drone_service

router = APIRouter(prefix="/drones", tags=["Drones"])


@router.get(
    "",
    response_model=DroneListResponse,
    summary="List all drones (filterable by status and location)",
)
async def list_drones(
    status: str | None = Query(
        None, pattern="^(available|rented|damaged|maintenance)$"
    ),
    location_id: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
):
    return await drone_service.list_drones(
        db,
        current_user=current_user,
        status_filter=status,
        location_id=location_id,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/{drone_id}",
    response_model=DroneResponse,
    summary="Get a single drone by ID",
)
async def get_drone(
    drone_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
):
    return await drone_service.get_drone_response(drone_id, db, current_user)


@router.post(
    "/{drone_id}/favorite",
    response_model=DroneResponse,
    summary="Favorite a drone",
)
async def favorite_drone(
    drone_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await drone_service.favorite_drone(drone_id, current_user, db)


@router.delete(
    "/{drone_id}/favorite",
    response_model=DroneResponse,
    summary="Remove a drone from favorites",
)
async def unfavorite_drone(
    drone_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await drone_service.unfavorite_drone(drone_id, current_user, db)
