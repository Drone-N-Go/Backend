"""
app/services/admin_service.py
-----------------------------
Business logic for the admin backend.
"""

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select
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
from app.models.drone import Drone
from app.models.locker_access_event import LockerAccessEvent
from app.models.locker_location import LockerLocation
from app.models.locker_unit import LockerUnit
from app.models.maintenance_task import MaintenanceTask
from app.models.smiota_event import SmiotaEvent
from app.models.user import User
from app.schemas.admin import (
    AdminBookingSummary,
    AdminDroneSummary,
    AdminProfileListResponse,
    AdminProfileResponse,
    AdminStatsResponse,
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
from app.schemas.user import UserResponse
from app.services import auth_service

ACTIVE_TASK_STATUSES = {"open", "in_progress"}
TERMINAL_BOOKING_STATUSES = {"returned", "cancelled"}


def _profile_response(profile: AdminProfile, assigned_location_ids: list[str] | None = None) -> AdminProfileResponse:
    return AdminProfileResponse(
        id=profile.id,
        user_id=profile.user_id,
        role=profile.role,
        status=profile.status,
        title=profile.title,
        phone=profile.phone,
        notes=profile.notes,
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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This admin role cannot manage the target role.",
        )


async def _get_admin_profile(profile_id: str, db: AsyncSession) -> AdminProfile:
    result = await db.execute(
        select(AdminProfile)
        .where(AdminProfile.id == profile_id)
        .options(selectinload(AdminProfile.user), selectinload(AdminProfile.location_assignments))
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin profile not found.")
    return profile


async def get_me(context: AdminContext) -> AdminProfileResponse:
    print(
        "ADMIN_TRACE get_me service "
        f"user_id={context.user.id} profile_id={context.profile.id} "
        f"role={context.profile.role} assigned_locations={len(context.assigned_location_ids)}"
    )
    return _profile_response(context.profile, sorted(context.assigned_location_ids))


async def setup_first_owner(body: OwnerSetupRequest, db: AsyncSession) -> OwnerSetupResponse:
    print(f"ADMIN_TRACE setup_first_owner start email={body.email}")
    active_count = (
        await db.execute(
            select(func.count()).select_from(AdminProfile).where(AdminProfile.status == "active")
        )
    ).scalar_one()
    print(f"ADMIN_TRACE setup_first_owner active_admin_count={active_count}")
    if active_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Owner setup is already complete.",
        )

    existing_user = await db.execute(select(User).where(User.email == body.email.lower()))
    if existing_user.scalar_one_or_none():
        print(f"ADMIN_TRACE setup_first_owner existing_user_conflict email={body.email}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    print(f"ADMIN_TRACE setup_first_owner creating_user email={body.email}")
    user = User(
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        first_name=body.first_name,
        last_name=body.last_name,
        role="user",
    )
    db.add(user)
    await db.flush()
    print(f"ADMIN_TRACE setup_first_owner user_flushed user_id={user.id}")

    profile = AdminProfile(
        user_id=user.id,
        role="owner",
        status="active",
        title=body.title,
        phone=body.phone,
    )
    db.add(profile)
    await db.flush()
    print(f"ADMIN_TRACE setup_first_owner profile_flushed profile_id={profile.id}")

    token_data = await auth_service.build_token_response(user, db)
    print(f"ADMIN_TRACE setup_first_owner token_created user_id={user.id}")
    await _audit(
        db,
        None,
        "admin.owner_setup",
        "admin_profile",
        profile.id,
        {"email": user.email},
    )
    print(f"ADMIN_TRACE setup_first_owner audit_written profile_id={profile.id}")

    profile.user = user
    print(f"ADMIN_TRACE setup_first_owner response_ready profile_id={profile.id}")
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
    target = await _get_admin_profile(profile_id, db)
    # Actor must be able to manage both the target's current role and the new role.
    _assert_can_manage_role(context.profile.role, target.role)
    _assert_can_manage_role(context.profile.role, new_role)
    old_role = target.role
    target.role = new_role
    db.add(target)
    await db.flush()
    await _audit(
        db,
        context,
        "admin.staff_role_updated",
        "admin_profile",
        target.id,
        {"old_role": old_role, "new_role": new_role},
    )
    return _profile_response(target, [a.location_id for a in target.location_assignments])


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
        courier_code=event.courier_code,
        tracking_id=event.tracking_id,
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
    event = await _latest_smiota_event_for_unit(unit, db)
    booking = await _active_booking_for_unit(unit, db)
    task_count = await _active_task_count(unit.id, db)
    passcode = event.passcode if event else None

    return LockerCurrentStateResponse(
        locker_unit_id=unit.id,
        location_id=unit.location_id,
        location_name=unit.location.campus_name if unit.location else "",
        unit_number=unit.unit_number,
        status=unit.status,
        smiota_locker_name=unit.smiota_locker_name,
        smiota_unit_identifier=unit.smiota_unit_identifier,
        has_current_passcode=bool(passcode),
        passcode_mask="••••••" if passcode else None,
        latest_tracking_id=event.tracking_id if event else None,
        latest_event=_event_summary(event),
        assigned_drone=_drone_summary(unit.current_drone),
        active_booking=_booking_summary(booking),
        maintenance_task_count=task_count,
    )


async def list_locker_current_state(
    context: AdminContext,
    db: AsyncSession,
    location_id: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> LockerCurrentStateListResponse:
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
    return LockerCurrentStateListResponse(
        items=[await _locker_state(unit, db) for unit in units],
        total=total,
        skip=skip,
        limit=limit,
    )


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
    event = await _latest_smiota_event_for_unit(unit, db)
    if not event or not event.passcode:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No current Smiota passcode is available for this locker.",
        )
    booking = await _active_booking_for_unit(unit, db)
    access_event = LockerAccessEvent(
        admin_profile_id=context.profile.id,
        locker_unit_id=unit.id,
        drone_id=unit.current_drone_id,
        booking_id=booking.id if booking else None,
        smiota_event_id=event.id,
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
            "smiota_event_id": event.id,
            "reason": body.reason,
        },
    )
    return PasscodeRevealResponse(
        locker_unit_id=unit.id,
        passcode=event.passcode,
        courier_code=event.courier_code,
        tracking_id=event.tracking_id,
        smiota_event_id=event.id,
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
