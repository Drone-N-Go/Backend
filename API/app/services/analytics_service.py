"""
app/services/analytics_service.py
-----------------------------------
Business logic for the admin analytics dashboard.
All queries use raw SQLAlchemy core expressions for performance.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import case, cast, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Numeric

from app.models.booking import Booking
from app.models.damage_report import DamageReport
from app.models.drone import Drone
from app.models.locker_location import LockerLocation
from app.models.user import User
from app.schemas.analytics import (
    AnalyticsResponse,
    BookingStatusBreakdown,
    DamageStats,
    DroneUtilization,
    OverviewStats,
    PopularRentalTime,
    RentalTypeBreakdown,
    RevenueByCampus,
)


async def get_analytics(days: int, db: AsyncSession) -> AnalyticsResponse:
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # ------------------------------------------------------------------ #
    # Overview
    # ------------------------------------------------------------------ #
    total_bookings = (
        await db.execute(select(func.count()).select_from(Booking))
    ).scalar_one()

    period_bookings = (
        await db.execute(
            select(func.count()).select_from(Booking).where(Booking.created_at >= since)
        )
    ).scalar_one()

    total_revenue = (
        await db.execute(
            select(func.coalesce(func.sum(Booking.total_cost), 0)).where(
                Booking.status == "completed"
            )
        )
    ).scalar_one()

    period_revenue = (
        await db.execute(
            select(func.coalesce(func.sum(Booking.total_cost), 0)).where(
                Booking.status == "completed", Booking.created_at >= since
            )
        )
    ).scalar_one()

    # Drone counts by status
    drone_counts = (
        await db.execute(
            select(Drone.status, func.count().label("cnt")).group_by(Drone.status)
        )
    ).all()
    drone_status_map = {row.status: row.cnt for row in drone_counts}

    total_drones = sum(drone_status_map.values())
    total_users = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    total_locations = (
        await db.execute(select(func.count()).select_from(LockerLocation))
    ).scalar_one()

    overview = OverviewStats(
        total_bookings=total_bookings,
        period_bookings=period_bookings,
        total_revenue=Decimal(str(total_revenue)),
        period_revenue=Decimal(str(period_revenue)),
        total_drones=total_drones,
        available_drones=drone_status_map.get("available", 0),
        rented_drones=drone_status_map.get("rented", 0),
        damaged_drones=drone_status_map.get("damaged", 0),
        maintenance_drones=drone_status_map.get("maintenance", 0),
        total_users=total_users,
        total_locations=total_locations,
    )

    # ------------------------------------------------------------------ #
    # Booking status breakdown
    # ------------------------------------------------------------------ #
    status_rows = (
        await db.execute(
            select(Booking.status, func.count().label("cnt")).group_by(Booking.status)
        )
    ).all()
    status_map = {row.status: row.cnt for row in status_rows}

    booking_status = BookingStatusBreakdown(
        pending=status_map.get("pending", 0),
        active=status_map.get("active", 0),
        completed=status_map.get("completed", 0),
        cancelled=status_map.get("cancelled", 0),
    )

    # ------------------------------------------------------------------ #
    # Revenue per campus
    # ------------------------------------------------------------------ #
    campus_rows = (
        await db.execute(
            select(
                LockerLocation.id.label("location_id"),
                LockerLocation.campus_name,
                func.coalesce(func.sum(Booking.total_cost), 0).label("revenue"),
                func.count(Booking.id).label("booking_count"),
            )
            .outerjoin(Booking, Booking.location_id == LockerLocation.id)
            .where((Booking.status == "completed") | (Booking.id == None))  # noqa: E711
            .group_by(LockerLocation.id, LockerLocation.campus_name)
        )
    ).all()

    revenue_per_campus = [
        RevenueByCampus(
            location_id=row.location_id,
            campus_name=row.campus_name,
            revenue=Decimal(str(row.revenue)),
            booking_count=row.booking_count,
            avg_booking_value=(
                Decimal(str(row.revenue)) / row.booking_count
                if row.booking_count > 0
                else Decimal("0")
            ),
        )
        for row in campus_rows
    ]

    # ------------------------------------------------------------------ #
    # Drone utilization
    # ------------------------------------------------------------------ #
    util_rows = (
        await db.execute(
            select(
                Drone.id.label("drone_id"),
                Drone.model_name,
                Drone.serial_number,
                func.count(Booking.id).label("total_bookings"),
                func.coalesce(func.sum(Booking.total_cost), 0).label("total_revenue"),
            )
            .outerjoin(Booking, Booking.drone_id == Drone.id)
            .group_by(Drone.id, Drone.model_name, Drone.serial_number)
        )
    ).all()

    drone_utilization = [
        DroneUtilization(
            drone_id=row.drone_id,
            model_name=row.model_name,
            serial_number=row.serial_number,
            total_bookings=row.total_bookings,
            total_revenue=Decimal(str(row.total_revenue)),
            utilization_percent=round(
                (row.total_bookings / max(total_bookings, 1)) * 100, 2
            ),
        )
        for row in util_rows
    ]

    # ------------------------------------------------------------------ #
    # Popular rental times (hour of day)
    # ------------------------------------------------------------------ #
    time_rows = (
        await db.execute(
            select(
                extract("hour", func.cast(Booking.pickup_time, db.bind.dialect.name == "postgresql" and "TIMESTAMPTZ" or "DATETIME")).label("hour"),
                func.count().label("cnt"),
            )
            .group_by("hour")
            .order_by("hour")
        )
    ).all()

    popular_times = [
        PopularRentalTime(hour=int(row.hour), booking_count=row.cnt) for row in time_rows
    ]

    # ------------------------------------------------------------------ #
    # Rental type breakdown
    # ------------------------------------------------------------------ #
    type_rows = (
        await db.execute(
            select(
                Booking.rental_type,
                func.count().label("cnt"),
                func.coalesce(func.sum(Booking.total_cost), 0).label("revenue"),
            )
            .group_by(Booking.rental_type)
        )
    ).all()
    type_map = {row.rental_type: row for row in type_rows}

    rental_type = RentalTypeBreakdown(
        hourly_count=type_map["hourly"].cnt if "hourly" in type_map else 0,
        daily_count=type_map["daily"].cnt if "daily" in type_map else 0,
        hourly_revenue=Decimal(str(type_map["hourly"].revenue)) if "hourly" in type_map else Decimal("0"),
        daily_revenue=Decimal(str(type_map["daily"].revenue)) if "daily" in type_map else Decimal("0"),
    )

    # ------------------------------------------------------------------ #
    # Damage stats
    # ------------------------------------------------------------------ #
    dmg_rows = (
        await db.execute(
            select(DamageReport.condition_status, func.count().label("cnt"))
            .group_by(DamageReport.condition_status)
        )
    ).all()
    dmg_map = {row.condition_status: row.cnt for row in dmg_rows}

    damage_stats = DamageStats(
        total_reports=sum(dmg_map.values()),
        needs_review=dmg_map.get("needs_review", 0),
        damaged=dmg_map.get("damaged", 0),
        undamaged=dmg_map.get("undamaged", 0),
    )

    return AnalyticsResponse(
        period_days=days,
        overview=overview,
        booking_status_breakdown=booking_status,
        revenue_per_campus=revenue_per_campus,
        drone_utilization=drone_utilization,
        popular_rental_times=popular_times,
        rental_type_breakdown=rental_type,
        damage_stats=damage_stats,
    )
