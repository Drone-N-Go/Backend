"""
app/schemas/analytics.py
-------------------------
Pydantic v2 response schemas for the analytics dashboard endpoint.
"""

from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


class OverviewStats(BaseModel):
    total_bookings: int
    period_bookings: int
    total_revenue: Decimal
    period_revenue: Decimal
    total_drones: int
    available_drones: int
    rented_drones: int
    damaged_drones: int
    maintenance_drones: int
    total_users: int
    total_locations: int


class BookingStatusBreakdown(BaseModel):
    pending: int
    active: int
    completed: int
    cancelled: int


class RevenueByCampus(BaseModel):
    location_id: str
    campus_name: str
    revenue: Decimal
    booking_count: int
    avg_booking_value: Decimal


class DroneUtilization(BaseModel):
    drone_id: str
    model_name: str
    serial_number: str
    total_bookings: int
    total_revenue: Decimal
    utilization_percent: float


class PopularRentalTime(BaseModel):
    hour: int
    booking_count: int


class RentalTypeBreakdown(BaseModel):
    hourly_count: int
    daily_count: int
    hourly_revenue: Decimal
    daily_revenue: Decimal


class DamageStats(BaseModel):
    total_reports: int
    needs_review: int
    damaged: int
    undamaged: int


class AnalyticsResponse(BaseModel):
    period_days: int
    overview: OverviewStats
    booking_status_breakdown: BookingStatusBreakdown
    revenue_per_campus: list[RevenueByCampus]
    drone_utilization: list[DroneUtilization]
    popular_rental_times: list[PopularRentalTime]
    rental_type_breakdown: RentalTypeBreakdown
    damage_stats: DamageStats
