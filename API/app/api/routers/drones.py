"""
app/api/routers/drones.py
--------------------------
Drone management endpoints:
  GET    /api/drones                        (public)
  GET    /api/drones/{drone_id}             (public)
  POST   /api/drones                        (admin)
  PUT    /api/drones/{drone_id}             (admin)
  DELETE /api/drones/{drone_id}             (admin)
  PATCH  /api/drones/{drone_id}/status      (admin)
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_optional_user, require_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.drone import (
    DroneCreateRequest,
    DroneListResponse,
    DroneResponse,
    DroneStatusRequest,
    DroneUpdateRequest,
)
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
    "",
    response_model=DroneResponse,
    status_code=201,
    summary="Create a new drone — admin only",
)
async def create_drone(
    body: DroneCreateRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    drone = await drone_service.create_drone(body, db)
    return await drone_service.get_drone_response(drone.id, db)


@router.put(
    "/{drone_id}",
    response_model=DroneResponse,
    summary="Update a drone — admin only",
)
async def update_drone(
    drone_id: str,
    body: DroneUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    drone = await drone_service.update_drone(drone_id, body, db)
    return await drone_service.get_drone_response(drone.id, db)


@router.delete(
    "/{drone_id}",
    status_code=204,
    summary="Delete a drone — admin only",
)
async def delete_drone(
    drone_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    await drone_service.delete_drone(drone_id, db)


@router.patch(
    "/{drone_id}/status",
    response_model=DroneResponse,
    summary="Override a drone's status — admin only",
)
async def update_drone_status(
    drone_id: str,
    body: DroneStatusRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    drone = await drone_service.update_drone_status(drone_id, body.status, db)
    return await drone_service.get_drone_response(drone.id, db)


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
