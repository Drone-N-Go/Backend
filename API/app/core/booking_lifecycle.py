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
    "no_show",
)

BOOKING_STATUS_PATTERN = "^(" + "|".join(BOOKING_STATUSES) + ")$"

TERMINAL_BOOKING_STATUSES = {"returned", "cancelled", "no_show"}

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

# Cancellation window rule (added 2026-09-01 for web booking-cancel support):
# - If pickup is at least this many hours away, cancellation is always free.
CANCELLATION_FREE_WINDOW_HOURS = 24
# - If pickup is already within the free window (a last-minute booking),
#   the user still gets this many hours from booking creation to cancel
#   penalty-free before the booking is locked in.
CANCELLATION_GRACE_PERIOD_HOURS = 2

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
    "no_show": "no_show_at",
}

# Surrender / no-show policy (added 2026-09-08 for the "never picked up,
# deadline passed" gap — see booking_service.surrender_booking() /
# _auto_expire_if_overdue()). A booking that is still `reserved` or
# `ready_for_pickup` (locker never opened) once its return deadline has
# passed can be surrendered by the user, or auto-expired server-side on
# next read, transitioning it to the terminal `no_show` status and
# freeing the drone.
NO_SHOW_REPEAT_THRESHOLD = 3
NO_SHOW_REPEAT_WINDOW_DAYS = 30

