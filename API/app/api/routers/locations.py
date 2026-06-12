"""
app/api/routers/locations.py
-----------------------------
Locker location and locker unit endpoints:
  GET    /api/locations                          (public)
  GET    /api/locations/{id}                     (public, includes units)
  GET    /api/locations/{id}/units               (public)
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.location import (
    LocationDetailResponse,
    LocationListResponse,
    LockerUnitListResponse,
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
