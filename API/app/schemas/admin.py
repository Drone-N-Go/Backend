"""
app/schemas/admin.py
--------------------
Pydantic schemas for Admin-iOS/Admin-Android backend APIs.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.admin_permissions import ADMIN_ROLES
from app.schemas.user import TokenResponse, UserResponse


ROLE_PATTERN = "^(" + "|".join(sorted(ADMIN_ROLES)) + ")$"


class AdminProfileResponse(BaseModel):
    id: str
    user_id: str
    role: str
    status: str
    title: Optional[str]
    phone: Optional[str]
    notes: Optional[str]
    must_change_password: bool = False
    created_at: datetime
    updated_at: datetime
    user: Optional[UserResponse] = None
    capabilities: list[str] = []
    assigned_location_ids: list[str] = []

    model_config = {"from_attributes": True}


class AdminMeResponse(BaseModel):
    profile: AdminProfileResponse


class OwnerSetupRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, description="Minimum 8 characters")
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    title: Optional[str] = None
    phone: Optional[str] = None


class OwnerSetupResponse(TokenResponse):
    admin_profile: AdminProfileResponse


class StaffCreateRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, description="Minimum 8 characters")
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    role: str = Field(..., pattern=ROLE_PATTERN)
    title: Optional[str] = None
    phone: Optional[str] = None
    notes: Optional[str] = None
    assigned_location_ids: list[str] = []


class StaffStatusRequest(BaseModel):
    status: str = Field(..., pattern="^(active|suspended)$")


class StaffRoleUpdateRequest(BaseModel):
    role: str = Field(..., pattern=ROLE_PATTERN)


class AdminProfileListResponse(BaseModel):
    items: list[AdminProfileResponse]
    total: int
    skip: int
    limit: int


class LockerMappingRequest(BaseModel):
    smiota_locker_name: Optional[str] = Field(None, max_length=255)
    smiota_unit_identifier: Optional[str] = Field(None, max_length=255)
    smiota_metadata: dict[str, Any] = {}


class LockerMaintenanceRequest(BaseModel):
    status: str = Field(..., pattern="^(available|occupied|maintenance)$")
    reason: str = Field(..., min_length=1)


class LockerDroneAssignmentRequest(BaseModel):
    drone_id: Optional[str] = None
    require_active_case_qr: bool = True


class SmiotaEventSummary(BaseModel):
    id: str
    notification_type: str
    object_id: str
    locker_name: Optional[str]
    courier_code: Optional[str]
    tracking_id: Optional[str]
    processed: bool
    processing_status: str
    error_message: Optional[str]
    created_at: datetime


class AdminDroneSummary(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    id: str
    model_name: str
    serial_number: str
    status: str
    image_urls: list[str] = []


class AdminBookingSummary(BaseModel):
    id: str
    user_id: str
    status: str
    pickup_time: str


class LockerCurrentStateResponse(BaseModel):
    id: str
    locker_unit_id: str
    location_id: str
    location_name: str
    unit_number: str
    status: str
    smiota_locker_name: Optional[str]
    smiota_unit_identifier: Optional[str]
    has_current_passcode: bool
    passcode_mask: Optional[str]
    latest_tracking_id: Optional[str]
    latest_event: Optional[SmiotaEventSummary]
    assigned_drone: Optional[AdminDroneSummary]
    active_booking: Optional[AdminBookingSummary]
    maintenance_task_count: int


class LockerCurrentStateListResponse(BaseModel):
    items: list[LockerCurrentStateResponse]
    total: int
    skip: int
    limit: int


class PasscodeRevealRequest(BaseModel):
    reason: str = Field(..., min_length=1)
    app_context: dict[str, Any] = {}


class PasscodeRevealResponse(BaseModel):
    locker_unit_id: str
    passcode: str
    courier_code: Optional[str]
    tracking_id: Optional[str]
    smiota_event_id: Optional[str]
    locker_access_event_id: str


class MaintenanceTaskCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    location_id: Optional[str] = None
    locker_unit_id: Optional[str] = None
    drone_id: Optional[str] = None
    assigned_admin_profile_id: Optional[str] = None
    priority: str = Field("normal", pattern="^(low|normal|high|urgent)$")


class MaintenanceTaskUpdateRequest(BaseModel):
    status: Optional[str] = Field(None, pattern="^(open|in_progress|resolved|cancelled)$")
    assigned_admin_profile_id: Optional[str] = None
    resolution_notes: Optional[str] = None


class MaintenanceTaskResponse(BaseModel):
    id: str
    location_id: Optional[str]
    locker_unit_id: Optional[str]
    drone_id: Optional[str]
    assigned_admin_profile_id: Optional[str]
    created_by_admin_profile_id: Optional[str]
    title: str
    description: Optional[str]
    status: str
    priority: str
    resolution_notes: Optional[str]
    resolved_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MaintenanceTaskListResponse(BaseModel):
    items: list[MaintenanceTaskResponse]
    total: int
    skip: int
    limit: int


class AdminLocationCreateRequest(BaseModel):
    campus_name: str = Field(..., min_length=1, max_length=255)
    locker_hardware_id: str = Field(..., min_length=1, max_length=255, description="Physical locker hardware identifier (e.g. 'A1', 'UNIT-01')")
    cabinet_count: int = Field(..., ge=1, le=50, description="Number of cabinets inside this locker")
    address: str = Field(..., min_length=1)
    latitude: float
    longitude: float
    building_name: Optional[str] = None
    landmarks: Optional[str] = None
    directions: Optional[str] = None


class AdminLockerUnitCreateRequest(BaseModel):
    unit_number: str = Field(..., min_length=1, max_length=50)


class DroneIntakeRequest(BaseModel):
    drone_id: Optional[str] = None
    serial_number: Optional[str] = Field(None, min_length=1, max_length=255)
    require_active_case_qr: bool = True
    photo_data: list[str] = Field(default_factory=list, description="Base64-encoded JPEG images")


class DroneIntakeResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    drone_id: str
    model_name: str
    serial_number: str
    locker_unit_id: str
    photo_urls: list[str]
    message: str


class AdminDroneLookupResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    id: str
    model_name: str
    serial_number: str
    status: str
    image_urls: list[str] = []


class AdminDroneSearchResponse(BaseModel):
    items: list[AdminDroneLookupResponse]
    total: int


class CaseQRGenerateRequest(BaseModel):
    action: str = Field("generate_new", pattern="^generate_new$")
    reason: str = Field(..., min_length=1, max_length=500)


class CaseQRVoidAndRegenerateRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


class CaseQRConfirmRequest(BaseModel):
    qr_payload: str = Field(..., min_length=1)


class CaseQRLookupRequest(BaseModel):
    qr_payload: str = Field(..., min_length=1)


class CaseQRTokenResponse(BaseModel):
    token_id: str
    drone_id: str
    status: str
    qr_payload: str
    label_title: str
    label_subtitle: str
    drone: AdminDroneSummary


class CaseQRTokenLookupResponse(BaseModel):
    token_id: str
    drone_id: str
    status: str
    drone: AdminDroneSummary


class AdminStatsResponse(BaseModel):
    role: str
    includes_money: bool
    total_users: int
    total_drones: int
    total_lockers: int
    open_maintenance_tasks: int
    active_bookings: int
    revenue_total: Optional[Decimal] = None
