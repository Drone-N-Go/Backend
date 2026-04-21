"""
app/api/routers/locations.py
-----------------------------
Locker location and locker unit endpoints:
  GET    /api/locations                          (public)
  GET    /api/locations/{id}                     (public, includes units)
  POST   /api/locations                          (admin)
  PUT    /api/locations/{id}                     (admin)
  DELETE /api/locations/{id}                     (admin)
  GET    /api/locations/{id}/units               (public)
  POST   /api/locations/{id}/units               (admin)
  PUT    /api/locations/{id}/units/{unit_id}     (admin)
  DELETE /api/locations/{id}/units/{unit_id}     (admin)
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_admin
from app.db.session import get_db
from app.models.user import User
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
from app.services import location_service

router = APIRouter(prefix="/locations", tags=["Locations & Lockers"])


# --------------------------------------------------------------------------- #
# Locations
# --------------------------------------------------------------------------- #

@router.get(
    "",
    response_model=LocationListResponse,
    summary="List all locker locations",
)
async def list_locations(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    return await location_service.list_locations(db, skip=skip, limit=limit)


@router.get(
    "/{location_id}",
    response_model=LocationDetailResponse,
    summary="Get a location with all its locker units",
)
async def get_location(location_id: str, db: AsyncSession = Depends(get_db)):
    location = await location_service.get_location(location_id, db)
    return LocationDetailResponse.model_validate(location)


@router.post(
    "",
    response_model=LocationResponse,
    status_code=201,
    summary="Create a new locker location — admin only",
)
async def create_location(
    body: LocationCreateRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    location = await location_service.create_location(body, db)
    return LocationResponse.model_validate(location)


@router.put(
    "/{location_id}",
    response_model=LocationResponse,
    summary="Update a locker location — admin only",
)
async def update_location(
    location_id: str,
    body: LocationUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    location = await location_service.update_location(location_id, body, db)
    return LocationResponse.model_validate(location)


@router.delete(
    "/{location_id}",
    status_code=204,
    summary="Delete a location and all its units — admin only",
)
async def delete_location(
    location_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    await location_service.delete_location(location_id, db)


# --------------------------------------------------------------------------- #
# Locker Units
# --------------------------------------------------------------------------- #

@router.get(
    "/{location_id}/units",
    response_model=LockerUnitListResponse,
    summary="List all locker units at a location",
)
async def list_units(
    location_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    return await location_service.list_units(location_id, db, skip=skip, limit=limit)


@router.post(
    "/{location_id}/units",
    response_model=LockerUnitResponse,
    status_code=201,
    summary="Add a locker unit to a location — admin only",
)
async def create_unit(
    location_id: str,
    body: LockerUnitCreateRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    unit = await location_service.create_unit(location_id, body, db)
    return LockerUnitResponse.model_validate(unit)


@router.put(
    "/{location_id}/units/{unit_id}",
    response_model=LockerUnitResponse,
    summary="Update a locker unit — admin only",
)
async def update_unit(
    location_id: str,
    unit_id: str,
    body: LockerUnitUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    unit = await location_service.update_unit(location_id, unit_id, body, db)
    return LockerUnitResponse.model_validate(unit)


@router.delete(
    "/{location_id}/units/{unit_id}",
    status_code=204,
    summary="Delete a locker unit — admin only",
)
async def delete_unit(
    location_id: str,
    unit_id: str,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    await location_service.delete_unit(location_id, unit_id, db)
