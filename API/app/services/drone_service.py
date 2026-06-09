"""
app/services/drone_service.py
------------------------------
Business logic for drone CRUD and status management.
"""

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.drone import Drone
from app.models.drone_favorite import DroneFavorite
from app.models.user import User
from app.schemas.drone import (
    AssignedLocationSummary,
    DroneCreateRequest,
    DroneListResponse,
    DroneResponse,
    DroneUpdateRequest,
)


def _drone_response(drone: Drone, favorite_ids: set[str] | None = None) -> DroneResponse:
    favorite_ids = favorite_ids or set()
    assigned_location = None
    if drone.assigned_location:
        assigned_location = AssignedLocationSummary(
            id=drone.assigned_location.id,
            campus_name=drone.assigned_location.campus_name,
            address=drone.assigned_location.address,
            latitude=drone.assigned_location.latitude,
            longitude=drone.assigned_location.longitude,
            building_name=drone.assigned_location.building_name,
        )

    return DroneResponse(
        id=drone.id,
        model_name=drone.model_name,
        subtitle=drone.subtitle,
        description=drone.description,
        category=drone.category,
        skill_level=drone.skill_level,
        serial_number=drone.serial_number,
        status=drone.status,
        assigned_locker_location_id=drone.assigned_locker_location_id,
        hourly_rate=drone.hourly_rate,
        daily_rate=drone.daily_rate,
        rating=drone.rating,
        review_count=drone.review_count,
        image_urls=list(drone.image_urls or []),
        standout_features=list(drone.standout_features or []),
        included_items=list(drone.included_items or []),
        rules=list(drone.rules or []),
        specs=dict(drone.specs or {}),
        is_favorite=drone.id in favorite_ids,
        assigned_location=assigned_location,
        created_at=drone.created_at,
        updated_at=drone.updated_at,
    )


async def _favorite_ids_for_user(
    db: AsyncSession, current_user: User | None, drone_ids: list[str] | None = None
) -> set[str]:
    if not current_user:
        return set()
    query = select(DroneFavorite.drone_id).where(DroneFavorite.user_id == current_user.id)
    if drone_ids is not None:
        query = query.where(DroneFavorite.drone_id.in_(drone_ids))
    result = await db.execute(query)
    return set(result.scalars().all())


async def list_drones(
    db: AsyncSession,
    current_user: User | None = None,
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
    drones = (
        await db.execute(
            query.options(selectinload(Drone.assigned_location)).offset(skip).limit(limit)
        )
    ).scalars().all()
    favorite_ids = await _favorite_ids_for_user(db, current_user, [d.id for d in drones])

    return DroneListResponse(
        items=[_drone_response(d, favorite_ids) for d in drones],
        total=total,
        skip=skip,
        limit=limit,
    )


async def get_drone(drone_id: str, db: AsyncSession) -> Drone:
    result = await db.execute(
        select(Drone).where(Drone.id == drone_id).options(selectinload(Drone.assigned_location))
    )
    drone = result.scalar_one_or_none()
    if not drone:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Drone not found.")
    return drone


async def get_drone_response(
    drone_id: str, db: AsyncSession, current_user: User | None = None
) -> DroneResponse:
    drone = await get_drone(drone_id, db)
    favorite_ids = await _favorite_ids_for_user(db, current_user, [drone.id])
    return _drone_response(drone, favorite_ids)


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
        subtitle=body.subtitle,
        description=body.description,
        category=body.category,
        skill_level=body.skill_level,
        serial_number=body.serial_number,
        assigned_locker_location_id=body.assigned_locker_location_id,
        hourly_rate=body.hourly_rate,
        daily_rate=body.daily_rate,
        rating=body.rating,
        review_count=body.review_count,
        image_urls=body.image_urls,
        standout_features=body.standout_features,
        included_items=body.included_items,
        rules=body.rules,
        specs=body.specs,
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


async def favorite_drone(drone_id: str, current_user: User, db: AsyncSession) -> DroneResponse:
    drone = await get_drone(drone_id, db)
    result = await db.execute(
        select(DroneFavorite).where(
            DroneFavorite.user_id == current_user.id,
            DroneFavorite.drone_id == drone_id,
        )
    )
    if not result.scalar_one_or_none():
        db.add(DroneFavorite(user_id=current_user.id, drone_id=drone_id))
        await db.flush()
    return _drone_response(drone, {drone_id})


async def unfavorite_drone(drone_id: str, current_user: User, db: AsyncSession) -> DroneResponse:
    drone = await get_drone(drone_id, db)
    await db.execute(
        delete(DroneFavorite).where(
            DroneFavorite.user_id == current_user.id,
            DroneFavorite.drone_id == drone_id,
        )
    )
    await db.flush()
    return _drone_response(drone, set())
