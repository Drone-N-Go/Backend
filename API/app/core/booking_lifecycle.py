"""
Shared booking lifecycle constants.
"""

BOOKING_STATUSES = (
    "reserved",
    "ready_for_pickup",
    "locker_opened",
    "case_verified",
    "before_photos_complete",
    "in_use",
    "return_started",
    "after_photos_complete",
    "return_locker_opened",
    "return_video_complete",
    "returned",
    "cancelled",
)

BOOKING_STATUS_PATTERN = "^(" + "|".join(BOOKING_STATUSES) + ")$"

TERMINAL_BOOKING_STATUSES = {"returned", "cancelled"}

BOOKING_TRANSITIONS = {
    "ready_for_pickup": "reserved",
    "locker_opened": "ready_for_pickup",
    "case_verified": "locker_opened",
    "before_photos_complete": "case_verified",
    "in_use": "before_photos_complete",
    "return_started": "in_use",
    "after_photos_complete": "return_started",
    "return_locker_opened": "after_photos_complete",
    "return_video_complete": "return_locker_opened",
    "returned": "return_video_complete",
}

BOOKING_STATUS_TIMESTAMP_FIELDS = {
    "ready_for_pickup": "ready_for_pickup_at",
    "locker_opened": "locker_opened_at",
    "case_verified": "case_verified_at",
    "before_photos_complete": "before_photos_completed_at",
    "in_use": "in_use_at",
    "return_started": "return_started_at",
    "after_photos_complete": "after_photos_completed_at",
    "return_locker_opened": "return_locker_opened_at",
    "return_video_complete": "return_video_completed_at",
    "returned": "returned_at",
    "cancelled": "cancelled_at",
}
