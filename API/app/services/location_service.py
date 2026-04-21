"""
app/services/location_service.py
---------------------------------
Business logic for locker locations and locker units.
"""

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.locker_location import LockerLocation
from app.models.locker_unit import LockerUnit
from app.schemas.location import (
    LocationCreateRequest,
    LocationDetailResponse,
    LocationListResponse,
    LocationResponse,
    LocationUpdateRequest,
    LockerUnitCreateRequest,
    LockerUnitListResponse,
    LockerUnitResponse,
    LockerUnitUpdateRequest,
)


# --------------------------------------------------------------------------- #
# Locations
# --------------------------------------------------------------------------- #

async def list_locations(
    db: AsyncSession, skip: int = 0, limit: int = 50
) -> LocationListResponse:
    total = (
        await db.execute(select(func.count()).select_from(LockerLocation))
    ).scalar_one()
    result = await db.execute(select(LockerLocation).offset(skip).limit(limit))
    locations = result.scalars().all()

    return LocationListResponse(
        items=[LocationResponse.model_validate(loc) for loc in locations],
        total=total,
        skip=skip,
        limit=limit,
    )


async def get_location(location_id: str, db: AsyncSession) -> LockerLocation:
    result = await db.execute(
        select(LockerLocation)
        .where(LockerLocation.id == location_id)
        .options(selectinload(LockerLocation.units))
    )
    location = result.scalar_one_or_none()
    if not location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Location not found."
        )
    return location


async def create_location(body: LocationCreateRequest, db: AsyncSession) -> LockerLocation:
    location = LockerLocation(
        campus_name=body.campus_name,
        address=body.address,
        latitude=body.latitude,
        longitude=body.longitude,
        building_name=body.building_name,
        landmarks=body.landmarks,
        directions=body.directions,
    )
    db.add(location)
    await db.flush()
    return location


async def update_location(
    location_id: str, body: LocationUpdateRequest, db: AsyncSession
) -> LockerLocation:
    location = await get_location(location_id, db)

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(location, field, value)

    db.add(location)
    await db.flush()
    return location


async def delete_location(location_id: str, db: AsyncSession) -> None:
    location = await get_location(location_id, db)
    await db.delete(location)
    await db.flush()


# --------------------------------------------------------------------------- #
# Locker Units
# --------------------------------------------------------------------------- #

async def list_units(
    location_id: str, db: AsyncSession, skip: int = 0, limit: int = 50
) -> LockerUnitListResponse:
    # Verify location exists
    await get_location(location_id, db)

    count_q = (
        await db.execute(
            select(func.count()).select_from(LockerUnit).where(LockerUnit.location_id == location_id)
        )
    ).scalar_one()

    result = await db.execute(
        select(LockerUnit)
        .where(LockerUnit.location_id == location_id)
        .offset(skip)
        .limit(limit)
    )
    units = result.scalars().all()

    return LockerUnitListResponse(
        items=[LockerUnitResponse.model_validate(u) for u in units],
        total=count_q,
        skip=skip,
        limit=limit,
    )


async def get_unit(location_id: str, unit_id: str, db: AsyncSession) -> LockerUnit:
    result = await db.execute(
        select(LockerUnit).where(
            LockerUnit.id == unit_id, LockerUnit.location_id == location_id
        )
    )
    unit = result.scalar_one_or_none()
    if not unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Locker unit not found."
        )
    return unit


async def create_unit(
    location_id: str, body: LockerUnitCreateRequest, db: AsyncSession
) -> LockerUnit:
    # Verify location exists
    await get_location(location_id, db)

    unit = LockerUnit(
        location_id=location_id,
        unit_number=body.unit_number,
        status=body.status,
    )
    db.add(unit)
    await db.flush()
    return unit


async def update_unit(
    location_id: str, unit_id: str, body: LockerUnitUpdateRequest, db: AsyncSession
) -> LockerUnit:
    unit = await get_unit(location_id, unit_id, db)

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(unit, field, value)

    db.add(unit)
    await db.flush()
    return unit


async def delete_unit(location_id: str, unit_id: str, db: AsyncSession) -> None:
    unit = await get_unit(location_id, unit_id, db)
    await db.delete(unit)
    await db.flush()
