"""
app/services/admin_service.py
-----------------------------
Business logic for the admin backend.
"""

import hmac
import logging
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.admin_permissions import (
    ADMIN,
    MANAGE_STAFF,
    VIEW_MONEY,
    can_manage_target_role,
    capabilities_for_role,
    has_global_location_scope,
    role_has_capability,
)
from app.core.dependencies import AdminContext
from app.core.security import hash_password
from app.models.admin_audit_event import AdminAuditEvent
from app.models.admin_profile import AdminLocationAssignment, AdminProfile
from app.models.booking import Booking
from app.models.case_qr_token import CaseQRToken
from app.models.drone import Drone
from app.models.locker_access_event import LockerAccessEvent
from app.models.locker_location import LockerLocation
from app.models.locker_unit import LockerUnit
from app.models.maintenance_task import MaintenanceTask
from app.models.smiota_event import SmiotaEvent
from app.models.user import User
from app.schemas.admin import (
    AdminBookingSummary,
    AdminDroneLookupResponse,
    AdminDroneSearchResponse,
    AdminDroneSummary,
    AdminProfileListResponse,
    AdminProfileResponse,
    AdminStatsResponse,
    CaseQRTokenLookupResponse,
    CaseQRTokenResponse,
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
)
from app.schemas.drone import DroneCreateRequest
from app.schemas.user import UserResponse
from app.services import auth_service
from app.services.case_qr_service import (
    case_qr_payload_for_token,
    create_pending_case_qr_token,
    extract_case_qr_token,
    find_case_qr_token_by_payload,
    hash_case_qr_token,
    retire_case_qr_token,
)

ACTIVE_TASK_STATUSES = {"open", "in_progress"}
TERMINAL_BOOKING_STATUSES = {"returned", "cancelled"}
logger = logging.getLogger(__name__)


def _admin_debug(message: str, **values) -> None:
    """Emit a debug-level structured log. Silenced in production via log-level config."""
    rendered_values = " ".join(f"{key}={value!r}" for key, value in values.items())
    line = f"ADMIN_DEBUG {message}"
    if rendered_values:
        line = f"{line} {rendered_values}"
    logger.debug(line)


def _profile_response(profile: AdminProfile, assigned_location_ids: list[str] | None = None) -> AdminProfileResponse:
    return AdminProfileResponse(
        id=profile.id,
        user_id=profile.user_id,
        role=profile.role,
        status=profile.status,
        title=profile.title,
        phone=profile.phone,
        notes=profile.notes,
        must_change_password=profile.must_change_password,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
        user=UserResponse.model_validate(profile.user) if profile.user else None,
        capabilities=sorted(capabilities_for_role(profile.role)),
        assigned_location_ids=assigned_location_ids or [],
    )


async def _assigned_location_ids(profile_id: str, db: AsyncSession) -> list[str]:
    result = await db.execute(
        select(AdminLocationAssignment.location_id).where(
            AdminLocationAssignment.admin_profile_id == profile_id
        )
    )
    return list(result.scalars().all())


async def _audit(
    db: AsyncSession,
    context: AdminContext | None,
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    details: dict | None = None,
) -> None:
    db.add(
        AdminAuditEvent(
            admin_profile_id=context.profile.id if context else None,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details or {},
        )
    )
    await db.flush()


def _assert_location_scope(context: AdminContext, location_id: str) -> None:
    if has_global_location_scope(context.profile.role):
        return
    if location_id not in context.assigned_location_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin is not assigned to this location.",
        )


def _assert_can_manage_role(actor_role: str, target_role: str) -> None:
    if not can_manage_target_role(actor_role, target_role):
        _admin_debug(
            "role_permission_denied",
            actor_role=actor_role,
            target_role=target_role,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This admin role cannot manage the target role.",
        )


async def _get_admin_profile(profile_id: str, db: AsyncSession) -> AdminProfile:
    _admin_debug("load_admin_profile_start", profile_id=profile_id)
    result = await db.execute(
        select(AdminProfile)
        .where(AdminProfile.id == profile_id)
        .options(selectinload(AdminProfile.user), selectinload(AdminProfile.location_assignments))
        .execution_options(populate_existing=True)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        _admin_debug("load_admin_profile_not_found", profile_id=profile_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin profile not found.")
    _admin_debug(
        "load_admin_profile_success",
        profile_id=profile.id,
        user_id=profile.user_id,
        role=profile.role,
        status=profile.status,
        assignment_count=len(profile.location_assignments),
    )
    return profile


async def get_me(context: AdminContext) -> AdminProfileResponse:
    return _profile_response(context.profile, sorted(context.assigned_location_ids))


async def setup_first_owner(body: OwnerSetupRequest, db: AsyncSession) -> OwnerSetupResponse:
    logger.info("setup_first_owner start")
    active_count = (
        await db.execute(
            select(func.count()).select_from(AdminProfile).where(AdminProfile.status == "active")
        )
    ).scalar_one()
    if active_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Owner setup is already complete.",
        )

    existing_user = await db.execute(select(User).where(User.email == body.email.lower()))
    if existing_user.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    user = User(
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        first_name=body.first_name,
        last_name=body.last_name,
        role="user",
    )
    db.add(user)
    await db.flush()

    profile = AdminProfile(
        user_id=user.id,
        role="owner",
        status="active",
        title=body.title,
        phone=body.phone,
        must_change_password=False,
    )
    db.add(profile)
    await db.flush()

    token_data = await auth_service.build_token_response(user, db)
    await _audit(
        db,
        None,
        "admin.owner_setup",
        "admin_profile",
        profile.id,
        {"email": user.email},
    )

    logger.info("setup_first_owner complete profile_id=%s", profile.id)
    profile.user = user
    return OwnerSetupResponse(
        access_token=token_data.access_token,
        refresh_token=token_data.refresh_token,
        token_type=token_data.token_type,
        user=token_data.user,
        admin_profile=_profile_response(profile, []),
    )


async def list_staff(context: AdminContext, db: AsyncSession, skip: int = 0, limit: int = 50) -> AdminProfileListResponse:
    if not role_has_capability(context.profile.role, MANAGE_STAFF):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Staff management access required.")

    total = (await db.execute(select(func.count()).select_from(AdminProfile))).scalar_one()
    result = await db.execute(
        select(AdminProfile)
        .options(selectinload(AdminProfile.user), selectinload(AdminProfile.location_assignments))
        .order_by(AdminProfile.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    profiles = result.scalars().all()
    return AdminProfileListResponse(
        items=[
            _profile_response(profile, [a.location_id for a in profile.location_assignments])
            for profile in profiles
        ],
        total=total,
        skip=skip,
        limit=limit,
    )


async def create_staff(context: AdminContext, body: StaffCreateRequest, db: AsyncSession) -> AdminProfileResponse:
    _assert_can_manage_role(context.profile.role, body.role)

    existing_user = await db.execute(select(User).where(User.email == body.email.lower()))
    if existing_user.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    user = User(
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        first_name=body.first_name,
        last_name=body.last_name,
        role="user",
    )
    db.add(user)
    await db.flush()

    profile = AdminProfile(
        user_id=user.id,
        role=body.role,
        status="active",
        title=body.title,
        phone=body.phone,
        notes=body.notes,
        must_change_password=True,
    )
    db.add(profile)
    await db.flush()

    for location_id in body.assigned_location_ids:
        db.add(AdminLocationAssignment(admin_profile_id=profile.id, location_id=location_id))
    await db.flush()

    await _audit(
        db,
        context,
        "admin.staff_create",
        "admin_profile",
        profile.id,
        {"role": profile.role, "assigned_location_ids": body.assigned_location_ids},
    )
    profile.user = user
    return _profile_response(profile, body.assigned_location_ids)


async def set_staff_status(
    context: AdminContext, profile_id: str, new_status: str, db: AsyncSession
) -> AdminProfileResponse:
    target = await _get_admin_profile(profile_id, db)
    _assert_can_manage_role(context.profile.role, target.role)
    target.status = new_status
    db.add(target)
    await db.flush()
    await _audit(
        db,
        context,
        "admin.staff_status",
        "admin_profile",
        target.id,
        {"status": new_status},
    )
    return _profile_response(target, [a.location_id for a in target.location_assignments])


async def update_staff_role(
    context: AdminContext, profile_id: str, new_role: str, db: AsyncSession
) -> AdminProfileResponse:
    _admin_debug(
        "update_staff_role_service_start",
        actor_profile_id=context.profile.id,
        actor_user_id=context.user.id,
        actor_role=context.profile.role,
        actor_capabilities=sorted(context.capabilities),
        actor_assigned_locations=sorted(context.assigned_location_ids),
        target_profile_id=profile_id,
        requested_role=new_role,
    )
    try:
        target = await _get_admin_profile(profile_id, db)
        _admin_debug(
            "update_staff_role_target_loaded",
            actor_profile_id=context.profile.id,
            target_profile_id=target.id,
            target_user_id=target.user_id,
            target_current_role=target.role,
            target_status=target.status,
            target_email=target.user.email if target.user else None,
        )
        _admin_debug(
            "update_staff_role_permission_check_current",
            actor_role=context.profile.role,
            target_current_role=target.role,
        )
        _assert_can_manage_role(context.profile.role, target.role)
        _admin_debug(
            "update_staff_role_permission_check_new",
            actor_role=context.profile.role,
            requested_role=new_role,
        )
        _assert_can_manage_role(context.profile.role, new_role)
        old_role = target.role
        target.role = new_role
        db.add(target)
        _admin_debug(
            "update_staff_role_flush_start",
            target_profile_id=target.id,
            old_role=old_role,
            new_role=new_role,
        )
        await db.flush()
        _admin_debug("update_staff_role_flush_success", target_profile_id=target.id)
        _admin_debug("update_staff_role_audit_start", target_profile_id=target.id)
        await _audit(
            db,
            context,
            "admin.staff_role_updated",
            "admin_profile",
            target.id,
            {"old_role": old_role, "new_role": new_role},
        )
        _admin_debug("update_staff_role_audit_success", target_profile_id=target.id)
        target = await _get_admin_profile(profile_id, db)
        assigned_location_ids = await _assigned_location_ids(target.id, db)
        _admin_debug(
            "update_staff_role_response_reload_success",
            target_profile_id=target.id,
            target_role=target.role,
            assigned_location_ids=assigned_location_ids,
        )
        response = _profile_response(target, assigned_location_ids)
        _admin_debug(
            "update_staff_role_response_ready",
            target_profile_id=response.id,
            response_role=response.role,
            response_user_id=response.user_id,
            response_capabilities=response.capabilities,
            response_assigned_location_ids=response.assigned_location_ids,
        )
        return response
    except SQLAlchemyError as exc:
        _admin_debug(
            "update_staff_role_sqlalchemy_error",
            actor_profile_id=context.profile.id,
            target_profile_id=profile_id,
            requested_role=new_role,
            exc_type=type(exc).__name__,
            exc=str(exc),
        )
        raise
    except Exception as exc:
        _admin_debug(
            "update_staff_role_unhandled_error",
            actor_profile_id=context.profile.id,
            target_profile_id=profile_id,
            requested_role=new_role,
            exc_type=type(exc).__name__,
            exc=str(exc),
        )
        raise


async def _latest_smiota_event_for_unit(unit: LockerUnit, db: AsyncSession) -> SmiotaEvent | None:
    criteria = []
    if unit.smiota_unit_identifier:
        criteria.append(SmiotaEvent.object_id == unit.smiota_unit_identifier)
    if unit.smiota_locker_name:
        criteria.append(SmiotaEvent.locker_name == unit.smiota_locker_name)
    if not criteria:
        return None

    result = await db.execute(
        select(SmiotaEvent).where(or_(*criteria)).order_by(SmiotaEvent.created_at.desc()).limit(1)
    )
    return result.scalar_one_or_none()


async def _active_booking_for_unit(unit: LockerUnit, db: AsyncSession) -> Booking | None:
    if not unit.current_drone_id:
        return None
    result = await db.execute(
        select(Booking)
        .where(
            Booking.drone_id == unit.current_drone_id,
            Booking.status.notin_(TERMINAL_BOOKING_STATUSES),
        )
        .order_by(Booking.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _active_task_count(unit_id: str, db: AsyncSession) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(MaintenanceTask)
            .where(
                MaintenanceTask.locker_unit_id == unit_id,
                MaintenanceTask.status.in_(ACTIVE_TASK_STATUSES),
            )
        )
    ).scalar_one()


def _event_summary(event: SmiotaEvent | None) -> SmiotaEventSummary | None:
    if not event:
        return None
    return SmiotaEventSummary(
        id=event.id,
        notification_type=event.notification_type,
        object_id=event.object_id,
        locker_name=event.locker_name,
        passcode=event.passcode,
        courier_code=event.courier_code,
        tracking_id=event.tracking_id,
        processed=event.processed,
        processing_status=event.processing_status,
        error_message=event.error_message,
        created_at=event.created_at,
    )


def _drone_summary(drone: Drone | None) -> AdminDroneSummary | None:
    if not drone:
        return None
    return AdminDroneSummary(
        id=drone.id,
        model_name=drone.model_name,
        serial_number=drone.serial_number,
        status=drone.status,
        image_urls=drone.image_urls or [],
    )


def _drone_lookup_response(drone: Drone) -> AdminDroneLookupResponse:
    return AdminDroneLookupResponse(
        id=drone.id,
        model_name=drone.model_name,
        serial_number=drone.serial_number,
        status=drone.status,
        image_urls=drone.image_urls or [],
    )


def _case_qr_response(token: CaseQRToken, drone: Drone) -> CaseQRTokenResponse:
    return CaseQRTokenResponse(
        token_id=token.id,
        drone_id=token.drone_id,
        status=token.status,
        qr_payload=case_qr_payload_for_token(token),
        label_title="DroneNGo Case Verification",
        label_subtitle=f"{drone.model_name} · {drone.serial_number}",
        drone=_drone_summary(drone),
    )


async def _get_admin_drone(drone_id: str, db: AsyncSession) -> Drone:
    result = await db.execute(select(Drone).where(Drone.id == drone_id))
    drone = result.scalar_one_or_none()
    if not drone:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Drone not found.")
    return drone


async def _get_case_qr_token(token_id: str, db: AsyncSession) -> CaseQRToken:
    result = await db.execute(select(CaseQRToken).where(CaseQRToken.id == token_id))
    token = result.scalar_one_or_none()
    if not token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case QR token not found.")
    return token


async def _assert_drone_has_active_case_qr(drone_id: str, db: AsyncSession) -> None:
    result = await db.execute(
        select(CaseQRToken).where(CaseQRToken.drone_id == drone_id, CaseQRToken.status == "active")
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Drone must have a confirmed active case QR before locker assignment.",
        )


def _booking_summary(booking: Booking | None) -> AdminBookingSummary | None:
    if not booking:
        return None
    return AdminBookingSummary(
        id=booking.id,
        user_id=booking.user_id,
        status=booking.status,
        pickup_time=booking.pickup_time,
    )


async def _locker_state(unit: LockerUnit, db: AsyncSession) -> LockerCurrentStateResponse:
    _admin_debug(
        "locker_state_build_start",
        locker_unit_id=unit.id,
        location_id=unit.location_id,
        unit_number=unit.unit_number,
        status=unit.status,
        smiota_locker_name=unit.smiota_locker_name,
        smiota_unit_identifier=unit.smiota_unit_identifier,
        current_drone_id=unit.current_drone_id,
    )
    event = await _latest_smiota_event_for_unit(unit, db)
    booking = await _active_booking_for_unit(unit, db)
    task_count = await _active_task_count(unit.id, db)
    # Passcode availability is authoritative on the unit itself.
    has_passcode = bool(unit.current_passcode)

    response = LockerCurrentStateResponse(
        id=unit.id,
        locker_unit_id=unit.id,
        location_id=unit.location_id,
        location_name=unit.location.campus_name if unit.location else "",
        unit_number=unit.unit_number,
        status=unit.status,
        smiota_locker_name=unit.smiota_locker_name,
        smiota_unit_identifier=unit.smiota_unit_identifier,
        has_current_passcode=has_passcode,
        passcode_mask="••••••" if has_passcode else None,
        latest_tracking_id=event.tracking_id if event else None,
        latest_event=_event_summary(event),
        assigned_drone=_drone_summary(unit.current_drone),
        active_booking=_booking_summary(booking),
        maintenance_task_count=task_count,
    )
    _admin_debug(
        "locker_state_build_success",
        id=response.id,
        locker_unit_id=response.locker_unit_id,
        has_current_passcode=response.has_current_passcode,
        latest_event_id=response.latest_event.id if response.latest_event else None,
        assigned_drone_id=response.assigned_drone.id if response.assigned_drone else None,
        active_booking_id=response.active_booking.id if response.active_booking else None,
        response_keys=sorted(response.model_dump(mode="json").keys()),
    )
    return response


async def list_locker_current_state(
    context: AdminContext,
    db: AsyncSession,
    location_id: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> LockerCurrentStateListResponse:
    _admin_debug(
        "locker_current_state_start",
        actor_profile_id=context.profile.id,
        actor_role=context.profile.role,
        location_id=location_id,
        skip=skip,
        limit=limit,
        assigned_location_ids=sorted(context.assigned_location_ids),
    )
    query = select(LockerUnit).options(
        selectinload(LockerUnit.location),
        selectinload(LockerUnit.current_drone),
    )
    count_query = select(func.count()).select_from(LockerUnit)

    if location_id:
        _assert_location_scope(context, location_id)
        query = query.where(LockerUnit.location_id == location_id)
        count_query = count_query.where(LockerUnit.location_id == location_id)
    elif not has_global_location_scope(context.profile.role):
        if not context.assigned_location_ids:
            return LockerCurrentStateListResponse(items=[], total=0, skip=skip, limit=limit)
        query = query.where(LockerUnit.location_id.in_(context.assigned_location_ids))
        count_query = count_query.where(LockerUnit.location_id.in_(context.assigned_location_ids))

    total = (await db.execute(count_query)).scalar_one()
    units = (
        await db.execute(query.order_by(LockerUnit.unit_number).offset(skip).limit(limit))
    ).scalars().all()
    _admin_debug(
        "locker_current_state_units_loaded",
        total=total,
        returned_units=len(units),
        locker_unit_ids=[unit.id for unit in units],
    )
    items = [await _locker_state(unit, db) for unit in units]
    response = LockerCurrentStateListResponse(
        items=items,
        total=total,
        skip=skip,
        limit=limit,
    )
    _admin_debug(
        "locker_current_state_response_ready",
        total=response.total,
        item_count=len(response.items),
        first_item=response.items[0].model_dump(mode="json") if response.items else None,
    )
    return response


async def _get_unit_for_admin(context: AdminContext, locker_unit_id: str, db: AsyncSession) -> LockerUnit:
    result = await db.execute(
        select(LockerUnit)
        .where(LockerUnit.id == locker_unit_id)
        .options(selectinload(LockerUnit.location), selectinload(LockerUnit.current_drone))
    )
    unit = result.scalar_one_or_none()
    if not unit:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Locker unit not found.")
    _assert_location_scope(context, unit.location_id)
    return unit


async def update_locker_mapping(
    context: AdminContext, locker_unit_id: str, body: LockerMappingRequest, db: AsyncSession
) -> LockerCurrentStateResponse:
    unit = await _get_unit_for_admin(context, locker_unit_id, db)
    unit.smiota_locker_name = body.smiota_locker_name
    unit.smiota_unit_identifier = body.smiota_unit_identifier
    unit.smiota_metadata = body.smiota_metadata
    db.add(unit)
    await db.flush()
    await _audit(db, context, "admin.locker_mapping", "locker_unit", unit.id, body.model_dump())
    return await _locker_state(unit, db)


async def update_locker_maintenance(
    context: AdminContext, locker_unit_id: str, body: LockerMaintenanceRequest, db: AsyncSession
) -> LockerCurrentStateResponse:
    unit = await _get_unit_for_admin(context, locker_unit_id, db)
    unit.status = body.status
    db.add(unit)
    await db.flush()
    await _audit(
        db,
        context,
        "admin.locker_status",
        "locker_unit",
        unit.id,
        {"status": body.status, "reason": body.reason},
    )
    return await _locker_state(unit, db)


async def assign_locker_drone(
    context: AdminContext, locker_unit_id: str, body: LockerDroneAssignmentRequest, db: AsyncSession
) -> LockerCurrentStateResponse:
    unit = await _get_unit_for_admin(context, locker_unit_id, db)
    drone = None
    if body.drone_id:
        result = await db.execute(select(Drone).where(Drone.id == body.drone_id))
        drone = result.scalar_one_or_none()
        if not drone:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Drone not found.")
        if body.require_active_case_qr:
            await _assert_drone_has_active_case_qr(drone.id, db)
        drone.assigned_locker_location_id = unit.location_id
        db.add(drone)
        unit.current_drone_id = drone.id
        if unit.status == "available":
            unit.status = "occupied"
    else:
        unit.current_drone_id = None
        if unit.status == "occupied":
            unit.status = "available"

    db.add(unit)
    await db.flush()
    await _audit(
        db,
        context,
        "admin.locker_drone_assignment",
        "locker_unit",
        unit.id,
        {"drone_id": body.drone_id},
    )
    unit.current_drone = drone
    return await _locker_state(unit, db)


async def reveal_locker_passcode(
    context: AdminContext, locker_unit_id: str, body: PasscodeRevealRequest, db: AsyncSession
) -> PasscodeRevealResponse:
    unit = await _get_unit_for_admin(context, locker_unit_id, db)
    if not unit.current_passcode:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No current passcode is available for this cabinet.",
        )
    # Still fetch the latest smiota event so we can surface tracking/courier info.
    event = await _latest_smiota_event_for_unit(unit, db)
    booking = await _active_booking_for_unit(unit, db)
    access_event = LockerAccessEvent(
        admin_profile_id=context.profile.id,
        locker_unit_id=unit.id,
        drone_id=unit.current_drone_id,
        booking_id=booking.id if booking else None,
        smiota_event_id=event.id if event else None,
        reason=body.reason,
        app_context=body.app_context,
    )
    db.add(access_event)
    await db.flush()
    await _audit(
        db,
        context,
        "admin.locker_passcode_reveal",
        "locker_unit",
        unit.id,
        {
            "locker_access_event_id": access_event.id,
            "smiota_event_id": event.id if event else None,
            "reason": body.reason,
        },
    )
    return PasscodeRevealResponse(
        locker_unit_id=unit.id,
        passcode=unit.current_passcode,
        courier_code=event.courier_code if event else None,
        tracking_id=event.tracking_id if event else None,
        smiota_event_id=event.id if event else None,
        locker_access_event_id=access_event.id,
    )


async def create_maintenance_task(
    context: AdminContext, body: MaintenanceTaskCreateRequest, db: AsyncSession
) -> MaintenanceTaskResponse:
    location_id = body.location_id
    if body.locker_unit_id:
        unit = await _get_unit_for_admin(context, body.locker_unit_id, db)
        location_id = unit.location_id
    if location_id:
        _assert_location_scope(context, location_id)

    task = MaintenanceTask(
        location_id=location_id,
        locker_unit_id=body.locker_unit_id,
        drone_id=body.drone_id,
        assigned_admin_profile_id=body.assigned_admin_profile_id,
        created_by_admin_profile_id=context.profile.id,
        title=body.title,
        description=body.description,
        priority=body.priority,
    )
    db.add(task)
    await db.flush()
    await _audit(db, context, "admin.maintenance_create", "maintenance_task", task.id)
    return MaintenanceTaskResponse.model_validate(task)


async def list_maintenance_tasks(
    context: AdminContext,
    db: AsyncSession,
    status_filter: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> MaintenanceTaskListResponse:
    query = select(MaintenanceTask)
    count_query = select(func.count()).select_from(MaintenanceTask)
    if status_filter:
        query = query.where(MaintenanceTask.status == status_filter)
        count_query = count_query.where(MaintenanceTask.status == status_filter)
    if not has_global_location_scope(context.profile.role):
        if not context.assigned_location_ids:
            return MaintenanceTaskListResponse(items=[], total=0, skip=skip, limit=limit)
        query = query.where(MaintenanceTask.location_id.in_(context.assigned_location_ids))
        count_query = count_query.where(MaintenanceTask.location_id.in_(context.assigned_location_ids))
    total = (await db.execute(count_query)).scalar_one()
    tasks = (
        await db.execute(query.order_by(MaintenanceTask.created_at.desc()).offset(skip).limit(limit))
    ).scalars().all()
    return MaintenanceTaskListResponse(
        items=[MaintenanceTaskResponse.model_validate(task) for task in tasks],
        total=total,
        skip=skip,
        limit=limit,
    )


async def update_maintenance_task(
    context: AdminContext, task_id: str, body: MaintenanceTaskUpdateRequest, db: AsyncSession
) -> MaintenanceTaskResponse:
    result = await db.execute(select(MaintenanceTask).where(MaintenanceTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maintenance task not found.")
    if task.location_id:
        _assert_location_scope(context, task.location_id)
    if body.status is not None:
        task.status = body.status
        if body.status == "resolved" and task.resolved_at is None:
            task.resolved_at = datetime.now(timezone.utc)
    if body.assigned_admin_profile_id is not None:
        task.assigned_admin_profile_id = body.assigned_admin_profile_id
    if body.resolution_notes is not None:
        task.resolution_notes = body.resolution_notes
    db.add(task)
    await db.flush()
    await _audit(db, context, "admin.maintenance_update", "maintenance_task", task.id, body.model_dump(exclude_none=True))
    return MaintenanceTaskResponse.model_validate(task)


async def get_stats(context: AdminContext, db: AsyncSession) -> AdminStatsResponse:
    includes_money = role_has_capability(context.profile.role, VIEW_MONEY)
    location_filter = None
    if not has_global_location_scope(context.profile.role):
        location_filter = context.assigned_location_ids

    total_users = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    drone_query = select(func.count()).select_from(Drone)
    locker_query = select(func.count()).select_from(LockerUnit)
    task_query = select(func.count()).select_from(MaintenanceTask).where(MaintenanceTask.status.in_(ACTIVE_TASK_STATUSES))
    booking_query = select(func.count()).select_from(Booking).where(Booking.status.notin_(TERMINAL_BOOKING_STATUSES))
    revenue_query = select(func.coalesce(func.sum(Booking.total_cost), 0)).where(Booking.status == "returned")

    if location_filter is not None:
        if not location_filter:
            return AdminStatsResponse(
                role=context.profile.role,
                includes_money=includes_money,
                total_users=0,
                total_drones=0,
                total_lockers=0,
                open_maintenance_tasks=0,
                active_bookings=0,
                revenue_total=None,
            )
        drone_query = drone_query.where(Drone.assigned_locker_location_id.in_(location_filter))
        locker_query = locker_query.where(LockerUnit.location_id.in_(location_filter))
        task_query = task_query.where(MaintenanceTask.location_id.in_(location_filter))
        booking_query = booking_query.where(Booking.location_id.in_(location_filter))
        revenue_query = revenue_query.where(Booking.location_id.in_(location_filter))

    revenue_total = None
    if includes_money:
        revenue_total = Decimal((await db.execute(revenue_query)).scalar_one())

    return AdminStatsResponse(
        role=context.profile.role,
        includes_money=includes_money,
        total_users=total_users if has_global_location_scope(context.profile.role) else 0,
        total_drones=(await db.execute(drone_query)).scalar_one(),
        total_lockers=(await db.execute(locker_query)).scalar_one(),
        open_maintenance_tasks=(await db.execute(task_query)).scalar_one(),
        active_bookings=(await db.execute(booking_query)).scalar_one(),
        revenue_total=revenue_total,
    )


async def create_admin_drone(
    context: AdminContext, body: DroneCreateRequest, db: AsyncSession
) -> AdminDroneLookupResponse:
    from app.services.drone_service import create_drone as _create_drone

    drone = await _create_drone(body, db)
    await _audit(
        db,
        context,
        "admin.drone_create",
        "drone",
        drone.id,
        {"serial_number": drone.serial_number, "model_name": drone.model_name},
    )
    return _drone_lookup_response(drone)


async def search_admin_drones(
    context: AdminContext,
    db: AsyncSession,
    *,
    q: str | None = None,
    serial_number: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> AdminDroneSearchResponse:
    query = select(Drone)
    count_query = select(func.count()).select_from(Drone)

    filters = []
    if serial_number:
        filters.append(Drone.serial_number == serial_number)
    if q:
        pattern = f"%{q}%"
        filters.append(or_(Drone.model_name.ilike(pattern), Drone.serial_number.ilike(pattern)))
    if filters:
        query = query.where(and_(*filters))
        count_query = count_query.where(and_(*filters))

    total = (await db.execute(count_query)).scalar_one()
    result = await db.execute(query.order_by(Drone.created_at.desc()).offset(skip).limit(limit))
    return AdminDroneSearchResponse(
        items=[_drone_lookup_response(drone) for drone in result.scalars().all()],
        total=total,
    )


async def generate_case_qr_token(
    context: AdminContext, drone_id: str, reason: str, db: AsyncSession
) -> CaseQRTokenResponse:
    drone = await _get_admin_drone(drone_id, db)

    existing_pending = await db.execute(
        select(CaseQRToken).where(
            CaseQRToken.drone_id == drone.id,
            CaseQRToken.status == "pending_printed",
        )
    )
    pending = existing_pending.scalar_one_or_none()
    if pending:
        return _case_qr_response(pending, drone)

    existing_active = await db.execute(
        select(CaseQRToken).where(CaseQRToken.drone_id == drone.id, CaseQRToken.status == "active")
    )
    if existing_active.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Drone already has an active case QR. Use void-and-regenerate to replace it.",
        )

    token = await create_pending_case_qr_token(drone, db, admin_profile_id=context.profile.id)
    await _audit(
        db,
        context,
        "admin.case_qr_generate",
        "case_qr_token",
        token.id,
        {"drone_id": drone.id, "reason": reason},
    )
    return _case_qr_response(token, drone)


async def get_case_qr_print_payload(
    context: AdminContext, token_id: str, db: AsyncSession
) -> CaseQRTokenResponse:
    token = await _get_case_qr_token(token_id, db)
    if token.status not in {"pending_printed", "active"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Case QR token is no longer printable.")
    drone = await _get_admin_drone(token.drone_id, db)
    return _case_qr_response(token, drone)


async def void_and_regenerate_case_qr_token(
    context: AdminContext, token_id: str, reason: str, db: AsyncSession
) -> CaseQRTokenResponse:
    token = await _get_case_qr_token(token_id, db)
    if token.status in {"voided", "rotated"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Case QR token is already inactive.")

    drone = await _get_admin_drone(token.drone_id, db)
    retire_case_qr_token(token, reason=reason)
    db.add(token)
    replacement = await create_pending_case_qr_token(drone, db, admin_profile_id=context.profile.id)
    await _audit(
        db,
        context,
        "admin.case_qr_void_and_regenerate",
        "case_qr_token",
        token.id,
        {"replacement_token_id": replacement.id, "drone_id": drone.id, "reason": reason},
    )
    return _case_qr_response(replacement, drone)


async def confirm_case_qr_token(
    context: AdminContext, token_id: str, qr_payload: str, db: AsyncSession
) -> CaseQRTokenResponse:
    token = await _get_case_qr_token(token_id, db)
    if token.status in {"voided", "rotated"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Case QR token is inactive.")

    scanned_hash = hash_case_qr_token(extract_case_qr_token(qr_payload))
    if not hmac.compare_digest(scanned_hash, token.token_hash):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Scanned QR does not match this token.")

    drone = await _get_admin_drone(token.drone_id, db)
    now = datetime.now(timezone.utc)
    if token.status == "pending_printed":
        active_result = await db.execute(
            select(CaseQRToken).where(
                CaseQRToken.drone_id == token.drone_id,
                CaseQRToken.status == "active",
                CaseQRToken.id != token.id,
            )
        )
        for active_token in active_result.scalars().all():
            retire_case_qr_token(active_token, reason="Replaced by confirmed printed QR.")
            db.add(active_token)
        token.status = "active"
    token.confirmed_by_admin_profile_id = context.profile.id
    token.confirmed_at = now
    db.add(token)
    await db.flush()
    await _audit(
        db,
        context,
        "admin.case_qr_confirm",
        "case_qr_token",
        token.id,
        {"drone_id": drone.id},
    )
    return _case_qr_response(token, drone)


async def lookup_case_qr_token(
    context: AdminContext, qr_payload: str, db: AsyncSession
) -> CaseQRTokenLookupResponse:
    token = await find_case_qr_token_by_payload(qr_payload, db)
    if not token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case QR token not found.")
    drone = await _get_admin_drone(token.drone_id, db)
    return CaseQRTokenLookupResponse(
        token_id=token.id,
        drone_id=token.drone_id,
        status=token.status,
        drone=_drone_summary(drone),
    )


async def create_admin_location(
    context: AdminContext, body: "AdminLocationCreateRequest", db: AsyncSession
) -> "LocationResponse":
    from app.services.location_service import create_location as _create_location
    from app.schemas.location import LocationCreateRequest, LocationResponse as _LocationResponse

    req = LocationCreateRequest(
        campus_name=body.campus_name,
        address=body.address,
        latitude=body.latitude,
        longitude=body.longitude,
        building_name=body.building_name,
        landmarks=body.landmarks,
        directions=body.directions,
    )
    location = await _create_location(req, db)

    # Persist the hardware ID on the location row.
    location.locker_hardware_id = body.locker_hardware_id
    db.add(location)

    # Bulk-create one LockerUnit per cabinet, pre-wired to the Smiota locker name.
    for n in range(1, body.cabinet_count + 1):
        unit = LockerUnit(
            location_id=location.id,
            unit_number=str(n),
            status="available",
            smiota_locker_name=body.locker_hardware_id,
        )
        db.add(unit)

    await db.flush()
    await db.refresh(location)
    await _audit(
        db,
        context,
        "admin.location_create",
        "locker_location",
        location.id,
        {
            "campus_name": location.campus_name,
            "locker_hardware_id": body.locker_hardware_id,
            "cabinet_count": body.cabinet_count,
        },
    )
    return _LocationResponse.model_validate(location)


async def delete_admin_location(context: AdminContext, location_id: str, db: AsyncSession) -> None:
    from app.services.location_service import delete_location as _delete_location

    await _delete_location(location_id, db)
    await _audit(db, context, "admin.location_delete", "locker_location", location_id, {})


async def create_admin_locker_unit(
    context: AdminContext, location_id: str, body: "AdminLockerUnitCreateRequest", db: AsyncSession
) -> "LockerUnitResponse":
    from app.services.location_service import create_unit as _create_unit
    from app.schemas.location import LockerUnitCreateRequest, LockerUnitResponse as _LockerUnitResponse

    _assert_location_scope(context, location_id)
    req = LockerUnitCreateRequest(unit_number=body.unit_number)
    unit = await _create_unit(location_id, req, db)
    await _audit(db, context, "admin.locker_unit_create", "locker_unit", unit.id, {"unit_number": unit.unit_number})
    return _LockerUnitResponse.model_validate(unit)


async def lookup_drone_by_serial(
    context: AdminContext, serial_number: str, db: AsyncSession
) -> "AdminDroneLookupResponse":
    result = await db.execute(select(Drone).where(Drone.serial_number == serial_number))
    drone = result.scalar_one_or_none()
    if not drone:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No drone found with that serial number.")
    return _drone_lookup_response(drone)


async def intake_drone(
    context: AdminContext, locker_unit_id: str, body: "DroneIntakeRequest", db: AsyncSession
) -> "DroneIntakeResponse":
    import base64
    from app.services.s3_service import upload_image_bytes
    from app.schemas.admin import DroneIntakeResponse

    unit = await _get_unit_for_admin(context, locker_unit_id, db)
    if unit.current_drone_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This locker unit already has a drone assigned.",
        )

    if body.drone_id:
        result = await db.execute(select(Drone).where(Drone.id == body.drone_id))
    elif body.serial_number:
        result = await db.execute(select(Drone).where(Drone.serial_number == body.serial_number))
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Either drone_id or serial_number is required.",
        )
    drone = result.scalar_one_or_none()
    if not drone:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Drone not found.")
    if body.require_active_case_qr:
        await _assert_drone_has_active_case_qr(drone.id, db)

    # Upload condition photos to S3
    photo_urls: list[str] = []
    for i, b64 in enumerate(body.photo_data):
        try:
            image_bytes = base64.b64decode(b64)
            url = await upload_image_bytes(
                image_bytes,
                content_type="image/jpeg",
                prefix=f"drone-intake/{drone.id}",
            )
            photo_urls.append(url)
        except Exception:
            _admin_debug("intake_photo_upload_failed", drone_id=drone.id, index=i)

    # Persist: update drone image_urls, assign to locker
    drone.image_urls = photo_urls if photo_urls else drone.image_urls
    drone.status = "available"
    drone.assigned_locker_location_id = unit.location_id
    db.add(drone)

    unit.current_drone_id = drone.id
    unit.status = "occupied"
    db.add(unit)
    await db.flush()

    await _audit(
        db,
        context,
        "admin.drone_intake",
        "locker_unit",
        unit.id,
        {"drone_id": drone.id, "serial_number": drone.serial_number, "photo_count": len(photo_urls)},
    )
    return DroneIntakeResponse(
        drone_id=drone.id,
        model_name=drone.model_name,
        serial_number=drone.serial_number,
        locker_unit_id=unit.id,
        photo_urls=photo_urls,
        message=f"{drone.model_name} successfully checked into locker {unit.unit_number}.",
    )


async def remove_drone_from_unit(
    context: AdminContext, locker_unit_id: str, db: AsyncSession
) -> "LockerCurrentStateResponse":
    from app.schemas.admin import LockerCurrentStateResponse  # noqa: F811

    unit = await _get_unit_for_admin(context, locker_unit_id, db)
    if not unit.current_drone_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This locker unit has no drone assigned.",
        )

    drone = unit.current_drone
    # Return drone to maintenance status and detach from location
    drone.status = "maintenance"
    drone.assigned_locker_location_id = None
    db.add(drone)

    unit.current_drone_id = None
    unit.status = "available"
    db.add(unit)
    await db.flush()

    await _audit(
        db,
        context,
        "admin.drone_removed_from_locker",
        "locker_unit",
        unit.id,
        {"drone_id": drone.id, "serial_number": drone.serial_number},
    )

    return await _locker_state(unit, db)


async def list_unmapped_smiota_events(context: AdminContext, db: AsyncSession, limit: int = 50) -> list[SmiotaEventSummary]:
    if not has_global_location_scope(context.profile.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Global admin scope required.")
    mapped_object_ids = select(LockerUnit.smiota_unit_identifier).where(LockerUnit.smiota_unit_identifier.is_not(None))
    mapped_locker_names = select(LockerUnit.smiota_locker_name).where(LockerUnit.smiota_locker_name.is_not(None))
    result = await db.execute(
        select(SmiotaEvent)
        .where(
            and_(
                SmiotaEvent.object_id.notin_(mapped_object_ids),
                or_(SmiotaEvent.locker_name.is_(None), SmiotaEvent.locker_name.notin_(mapped_locker_names)),
            )
        )
        .order_by(SmiotaEvent.created_at.desc())
        .limit(limit)
    )
    return [_event_summary(event) for event in result.scalars().all()]


async def list_smiota_events(context: AdminContext, db: AsyncSession, limit: int = 100, skip: int = 0) -> list[SmiotaEventSummary]:
    if not has_global_location_scope(context.profile.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Global admin scope required.")
    result = await db.execute(
        select(SmiotaEvent)
        .order_by(SmiotaEvent.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return [_event_summary(event) for event in result.scalars().all()]
