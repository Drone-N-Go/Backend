"""
app/services/drone_service.py
------------------------------
Business logic for drone CRUD and status management.
"""

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drone import Drone
from app.schemas.drone import (
    DroneCreateRequest,
    DroneListResponse,
    DroneResponse,
    DroneUpdateRequest,
)


async def list_drones(
    db: AsyncSession,
    status_filter: str | None = None,
    location_id: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> DroneListResponse:
    query = select(Drone)
    count_query = select(func.count()).select_from(Drone)

    if status_filter:
        query = query.where(Drone.status == status_filter)
        count_query = count_query.where(Drone.status == status_filter)
    if location_id:
        query = query.where(Drone.assigned_locker_location_id == location_id)
        count_query = count_query.where(Drone.assigned_locker_location_id == location_id)

    total = (await db.execute(count_query)).scalar_one()
    drones = (await db.execute(query.offset(skip).limit(limit))).scalars().all()

    return DroneListResponse(
        items=[DroneResponse.model_validate(d) for d in drones],
        total=total,
        skip=skip,
        limit=limit,
    )


async def get_drone(drone_id: str, db: AsyncSession) -> Drone:
    result = await db.execute(select(Drone).where(Drone.id == drone_id))
    drone = result.scalar_one_or_none()
    if not drone:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Drone not found.")
    return drone


async def create_drone(body: DroneCreateRequest, db: AsyncSession) -> Drone:
    # Enforce unique serial number
    existing = await db.execute(
        select(Drone).where(Drone.serial_number == body.serial_number)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A drone with serial number '{body.serial_number}' already exists.",
        )

    drone = Drone(
        model_name=body.model_name,
        serial_number=body.serial_number,
        assigned_locker_location_id=body.assigned_locker_location_id,
        hourly_rate=body.hourly_rate,
        daily_rate=body.daily_rate,
        status="available",
    )
    db.add(drone)
    await db.flush()
    return drone


async def update_drone(drone_id: str, body: DroneUpdateRequest, db: AsyncSession) -> Drone:
    drone = await get_drone(drone_id, db)

    if body.model_name is not None:
        drone.model_name = body.model_name
    if body.serial_number is not None:
        # Check uniqueness if changing serial
        if body.serial_number != drone.serial_number:
            existing = await db.execute(
                select(Drone).where(Drone.serial_number == body.serial_number)
            )
            if existing.scalar_one_or_none():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Serial number '{body.serial_number}' is already in use.",
                )
        drone.serial_number = body.serial_number
    if body.assigned_locker_location_id is not None:
        drone.assigned_locker_location_id = body.assigned_locker_location_id
    if body.hourly_rate is not None:
        drone.hourly_rate = body.hourly_rate
    if body.daily_rate is not None:
        drone.daily_rate = body.daily_rate

    db.add(drone)
    await db.flush()
    return drone


async def delete_drone(drone_id: str, db: AsyncSession) -> None:
    drone = await get_drone(drone_id, db)
    await db.delete(drone)
    await db.flush()


async def update_drone_status(drone_id: str, new_status: str, db: AsyncSession) -> Drone:
    drone = await get_drone(drone_id, db)
    drone.status = new_status
    db.add(drone)
    await db.flush()
    return drone
