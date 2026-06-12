"""
app/api/routers/admin.py
-------------------------
Admin backend endpoints for Admin-iOS and future Admin-Android.
"""

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_permissions import (
    CREATE_MAINTENANCE_TASK,
    MANAGE_DRONES,
    MANAGE_LOCATIONS,
    MANAGE_LOCKERS,
    MANAGE_STAFF,
    RESOLVE_MAINTENANCE_TASK,
    REVEAL_LOCKER_PASSCODE,
    VIEW_LOCKER_STATE,
)
from app.core.dependencies import AdminContext, require_admin_profile, require_capability
from app.db.session import get_db
from app.schemas.admin import (
    AdminDroneLookupResponse,
    AdminLocationCreateRequest,
    AdminLockerUnitCreateRequest,
    AdminMeResponse,
    AdminProfileListResponse,
    AdminProfileResponse,
    AdminStatsResponse,
    DroneIntakeRequest,
    DroneIntakeResponse,
    LockerCurrentStateListResponse,
    LockerCurrentStateResponse,
    LockerDroneAssignmentRequest,
    LockerMaintenanceRequest,
    LockerMappingRequest,
    MaintenanceTaskCreateRequest,
    MaintenanceTaskListResponse,
    MaintenanceTaskResponse,
    MaintenanceTaskUpdateRequest,
    OwnerSetupRequest,
    OwnerSetupResponse,
    PasscodeRevealRequest,
    PasscodeRevealResponse,
    SmiotaEventSummary,
    StaffCreateRequest,
    StaffRoleUpdateRequest,
    StaffStatusRequest,
)
from app.schemas.location import LocationResponse, LockerUnitResponse
from app.services import admin_service

router = APIRouter(prefix="/admin", tags=["Admin"])
logger = logging.getLogger(__name__)


def _admin_route_debug(message: str, **values) -> None:
    rendered_values = " ".join(f"{key}={value!r}" for key, value in values.items())
    line = f"ADMIN_DEBUG_ROUTE {message}"
    if rendered_values:
        line = f"{line} {rendered_values}"
    logger.error(line)
    print(line, flush=True)


@router.post(
    "/setup/owner",
    response_model=OwnerSetupResponse,
    status_code=201,
    summary="Create the first Owner admin profile",
)
async def setup_owner(
    body: OwnerSetupRequest,
    db: AsyncSession = Depends(get_db),
):
    logger.info("ADMIN_TRACE setup_owner route start email=%s", body.email)
    try:
        response = await admin_service.setup_first_owner(body, db)
        logger.info("ADMIN_TRACE setup_owner route success user_id=%s", response.user.id)
        return response
    except Exception:
        logger.exception("ADMIN_TRACE setup_owner route failed email=%s", body.email)
        raise


@router.get(
    "/me",
    response_model=AdminMeResponse,
    summary="Get the current admin profile and capabilities",
)
async def me(context: AdminContext = Depends(require_admin_profile)):
    logger.info(
        "ADMIN_TRACE admin_me route start user_id=%s profile_id=%s",
        context.user.id,
        context.profile.id,
    )
    try:
        profile = await admin_service.get_me(context)
        logger.info("ADMIN_TRACE admin_me route success profile_id=%s", profile.id)
        return AdminMeResponse(profile=profile)
    except Exception:
        logger.exception("ADMIN_TRACE admin_me route failed profile_id=%s", context.profile.id)
        raise


@router.get(
    "/staff",
    response_model=AdminProfileListResponse,
    summary="List admin staff profiles",
)
async def list_staff(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    context: AdminContext = Depends(require_capability(MANAGE_STAFF)),
):
    return await admin_service.list_staff(context, db, skip=skip, limit=limit)


@router.post(
    "/staff",
    response_model=AdminProfileResponse,
    status_code=201,
    summary="Create an admin staff profile",
)
async def create_staff(
    body: StaffCreateRequest,
    db: AsyncSession = Depends(get_db),
    context: AdminContext = Depends(require_capability(MANAGE_STAFF)),
):
    return await admin_service.create_staff(context, body, db)


@router.patch(
    "/staff/{profile_id}/status",
    response_model=AdminProfileResponse,
    summary="Suspend or reactivate an admin staff profile",
)
async def set_staff_status(
    profile_id: str,
    body: StaffStatusRequest,
    db: AsyncSession = Depends(get_db),
    context: AdminContext = Depends(require_capability(MANAGE_STAFF)),
):
    return await admin_service.set_staff_status(context, profile_id, body.status, db)


@router.patch(
    "/staff/{profile_id}/role",
    response_model=AdminProfileResponse,
    summary="Update the role of an admin staff profile",
)
async def update_staff_role(
    profile_id: str,
    body: StaffRoleUpdateRequest,
    db: AsyncSession = Depends(get_db),
    context: AdminContext = Depends(require_capability(MANAGE_STAFF)),
):
    _admin_route_debug(
        "update_staff_role_start",
        actor_profile_id=context.profile.id,
        actor_user_id=context.user.id,
        actor_role=context.profile.role,
        actor_capabilities=sorted(context.capabilities),
        target_profile_id=profile_id,
        request_body=body.model_dump(mode="json"),
    )
    try:
        response = await admin_service.update_staff_role(context, profile_id, body.role, db)
        payload = response.model_dump(mode="json")
        _admin_route_debug(
            "update_staff_role_success_before_fastapi_response",
            actor_profile_id=context.profile.id,
            target_profile_id=response.id,
            response_payload=payload,
            response_keys=sorted(payload.keys()),
        )
        return response
    except Exception as exc:
        _admin_route_debug(
            "update_staff_role_failed",
            actor_profile_id=context.profile.id,
            actor_user_id=context.user.id,
            actor_role=context.profile.role,
            target_profile_id=profile_id,
            request_body=body.model_dump(mode="json"),
            exc_type=type(exc).__name__,
            exc=str(exc),
        )
        logger.exception("ADMIN_DEBUG_ROUTE update_staff_role_failed_traceback")
        raise


@router.get(
    "/lockers/current-state",
    response_model=LockerCurrentStateListResponse,
    summary="List current locker state with masked passcode availability",
)
async def locker_current_state(
    location_id: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    context: AdminContext = Depends(require_capability(VIEW_LOCKER_STATE)),
):
    _admin_route_debug(
        "locker_current_state_start",
        actor_profile_id=context.profile.id,
        actor_user_id=context.user.id,
        actor_role=context.profile.role,
        location_id=location_id,
        skip=skip,
        limit=limit,
    )
    try:
        response = await admin_service.list_locker_current_state(
            context, db, location_id=location_id, skip=skip, limit=limit
        )
        first_item = response.items[0].model_dump(mode="json") if response.items else None
        _admin_route_debug(
            "locker_current_state_success_before_fastapi_response",
            actor_profile_id=context.profile.id,
            total=response.total,
            item_count=len(response.items),
            first_item=first_item,
        )
        return response
    except Exception as exc:
        _admin_route_debug(
            "locker_current_state_failed",
            actor_profile_id=context.profile.id,
            actor_user_id=context.user.id,
            actor_role=context.profile.role,
            location_id=location_id,
            exc_type=type(exc).__name__,
            exc=str(exc),
        )
        logger.exception("ADMIN_DEBUG_ROUTE locker_current_state_failed_traceback")
        raise


@router.post(
    "/lockers/{locker_unit_id}/reveal-passcode",
    response_model=PasscodeRevealResponse,
    summary="Reveal the current locker passcode and write an audit record",
)
async def reveal_passcode(
    locker_unit_id: str,
    body: PasscodeRevealRequest,
    db: AsyncSession = Depends(get_db),
    context: AdminContext = Depends(require_capability(REVEAL_LOCKER_PASSCODE)),
):
    return await admin_service.reveal_locker_passcode(context, locker_unit_id, body, db)


@router.patch(
    "/lockers/{locker_unit_id}/mapping",
    response_model=LockerCurrentStateResponse,
    summary="Update explicit Smiota mapping for a locker unit",
)
async def update_locker_mapping(
    locker_unit_id: str,
    body: LockerMappingRequest,
    db: AsyncSession = Depends(get_db),
    context: AdminContext = Depends(require_capability(MANAGE_LOCKERS)),
):
    return await admin_service.update_locker_mapping(context, locker_unit_id, body, db)


@router.patch(
    "/lockers/{locker_unit_id}/maintenance",
    response_model=LockerCurrentStateResponse,
    summary="Update locker maintenance status",
)
async def update_locker_maintenance(
    locker_unit_id: str,
    body: LockerMaintenanceRequest,
    db: AsyncSession = Depends(get_db),
    context: AdminContext = Depends(require_capability(MANAGE_LOCKERS)),
):
    return await admin_service.update_locker_maintenance(context, locker_unit_id, body, db)


@router.patch(
    "/lockers/{locker_unit_id}/drone",
    response_model=LockerCurrentStateResponse,
    summary="Assign or unassign a drone from a locker unit",
)
async def assign_locker_drone(
    locker_unit_id: str,
    body: LockerDroneAssignmentRequest,
    db: AsyncSession = Depends(get_db),
    context: AdminContext = Depends(require_capability(MANAGE_DRONES)),
):
    return await admin_service.assign_locker_drone(context, locker_unit_id, body, db)


@router.post(
    "/locations",
    response_model=LocationResponse,
    status_code=201,
    summary="Create a new locker location",
)
async def create_location(
    body: AdminLocationCreateRequest,
    db: AsyncSession = Depends(get_db),
    context: AdminContext = Depends(require_capability(MANAGE_LOCATIONS)),
):
    return await admin_service.create_admin_location(context, body, db)


@router.delete(
    "/locations/{location_id}",
    status_code=204,
    summary="Delete a locker location and all its units",
)
async def delete_location(
    location_id: str,
    db: AsyncSession = Depends(get_db),
    context: AdminContext = Depends(require_capability(MANAGE_LOCATIONS)),
):
    await admin_service.delete_admin_location(context, location_id, db)


@router.post(
    "/locations/{location_id}/units",
    response_model=LockerUnitResponse,
    status_code=201,
    summary="Add a locker unit to a location",
)
async def create_locker_unit(
    location_id: str,
    body: AdminLockerUnitCreateRequest,
    db: AsyncSession = Depends(get_db),
    context: AdminContext = Depends(require_capability(MANAGE_LOCKERS)),
):
    return await admin_service.create_admin_locker_unit(context, location_id, body, db)


@router.get(
    "/drones/lookup",
    response_model=AdminDroneLookupResponse,
    summary="Look up a drone by serial number (from QR scan)",
)
async def lookup_drone_by_serial(
    serial_number: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
    context: AdminContext = Depends(require_capability(MANAGE_DRONES)),
):
    return await admin_service.lookup_drone_by_serial(context, serial_number, db)


@router.post(
    "/lockers/{locker_unit_id}/intake",
    response_model=DroneIntakeResponse,
    status_code=201,
    summary="Intake a drone into a locker — assigns drone, stores condition photos",
)
async def intake_drone(
    locker_unit_id: str,
    body: DroneIntakeRequest,
    db: AsyncSession = Depends(get_db),
    context: AdminContext = Depends(require_capability(MANAGE_DRONES)),
):
    return await admin_service.intake_drone(context, locker_unit_id, body, db)


@router.get(
    "/maintenance/tasks",
    response_model=MaintenanceTaskListResponse,
    summary="List maintenance tasks in admin scope",
)
async def list_maintenance_tasks(
    status_filter: str | None = Query(None, pattern="^(open|in_progress|resolved|cancelled)$"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    context: AdminContext = Depends(require_admin_profile),
):
    return await admin_service.list_maintenance_tasks(
        context, db, status_filter=status_filter, skip=skip, limit=limit
    )


@router.post(
    "/maintenance/tasks",
    response_model=MaintenanceTaskResponse,
    status_code=201,
    summary="Create a maintenance task",
)
async def create_maintenance_task(
    body: MaintenanceTaskCreateRequest,
    db: AsyncSession = Depends(get_db),
    context: AdminContext = Depends(require_capability(CREATE_MAINTENANCE_TASK)),
):
    return await admin_service.create_maintenance_task(context, body, db)


@router.patch(
    "/maintenance/tasks/{task_id}",
    response_model=MaintenanceTaskResponse,
    summary="Update a maintenance task",
)
async def update_maintenance_task(
    task_id: str,
    body: MaintenanceTaskUpdateRequest,
    db: AsyncSession = Depends(get_db),
    context: AdminContext = Depends(require_capability(RESOLVE_MAINTENANCE_TASK)),
):
    return await admin_service.update_maintenance_task(context, task_id, body, db)


@router.get(
    "/stats",
    response_model=AdminStatsResponse,
    summary="Get role-aware admin stats",
)
async def stats(
    db: AsyncSession = Depends(get_db),
    context: AdminContext = Depends(require_admin_profile),
):
    return await admin_service.get_stats(context, db)


@router.get(
    "/smiota/unmapped-events",
    response_model=list[SmiotaEventSummary],
    summary="List recent Smiota events that do not map to a locker unit",
)
async def unmapped_smiota_events(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    context: AdminContext = Depends(require_admin_profile),
):
    return await admin_service.list_unmapped_smiota_events(context, db, limit=limit)
