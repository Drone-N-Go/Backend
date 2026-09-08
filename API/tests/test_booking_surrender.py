from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest import TestCase

from app.models.booking import Booking
from app.services.booking_service import (
    _compute_return_deadline,
    _is_overdue_never_picked_up,
)


def make_booking(
    pickup_time: str,
    status: str = "reserved",
    rental_type: str = "hourly",
    rental_duration: int = 4,
) -> Booking:
    return Booking(
        user_id="user-id",
        drone_id="drone-id",
        location_id="location-id",
        pickup_time=pickup_time,
        rental_duration=rental_duration,
        rental_type=rental_type,
        status=status,
        total_cost=Decimal("100.00"),
    )


class ComputeReturnDeadlineTests(TestCase):
    def test_hourly_deadline_is_pickup_plus_duration_hours(self):
        booking = make_booking("2026-09-05T10:00:00Z", rental_type="hourly", rental_duration=5)
        deadline = _compute_return_deadline(booking)
        self.assertEqual(deadline, datetime(2026, 9, 5, 15, 0, tzinfo=timezone.utc))

    def test_daily_deadline_is_pickup_plus_duration_days(self):
        booking = make_booking("2026-09-05T10:00:00Z", rental_type="daily", rental_duration=2)
        deadline = _compute_return_deadline(booking)
        self.assertEqual(deadline, datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc))

    def test_unparseable_pickup_time_returns_none(self):
        booking = make_booking("not-a-date")
        self.assertIsNone(_compute_return_deadline(booking))


class IsOverdueNeverPickedUpTests(TestCase):
    def test_reserved_and_past_deadline_is_overdue(self):
        past_pickup = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()
        booking = make_booking(past_pickup, status="reserved", rental_duration=1)
        self.assertTrue(_is_overdue_never_picked_up(booking))

    def test_ready_for_pickup_and_past_deadline_is_overdue(self):
        past_pickup = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()
        booking = make_booking(past_pickup, status="ready_for_pickup", rental_duration=1)
        self.assertTrue(_is_overdue_never_picked_up(booking))

    def test_reserved_but_not_yet_past_deadline_is_not_overdue(self):
        future_pickup = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        booking = make_booking(future_pickup, status="reserved", rental_duration=4)
        self.assertFalse(_is_overdue_never_picked_up(booking))

    def test_already_picked_up_is_never_overdue_for_surrender_purposes(self):
        # Locker already opened — this is the "use the return flow instead"
        # branch, not surrender/no-show, regardless of how late it is.
        past_pickup = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()
        for status in (
            "locker_opened",
            "case_verified",
            "before_photos_complete",
            "in_use",
            "return_started",
        ):
            with self.subTest(status=status):
                booking = make_booking(past_pickup, status=status, rental_duration=1)
                self.assertFalse(_is_overdue_never_picked_up(booking))

    def test_terminal_statuses_are_never_overdue(self):
        past_pickup = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()
        for status in ("returned", "cancelled", "no_show"):
            with self.subTest(status=status):
                booking = make_booking(past_pickup, status=status, rental_duration=1)
                self.assertFalse(_is_overdue_never_picked_up(booking))

    def test_unparseable_pickup_time_fails_closed(self):
        # Unlike _is_cancellable (fails open), surrender eligibility fails
        # CLOSED on unparseable data since it's a punitive, no-show-counting
        # action — see _is_overdue_never_picked_up's docstring.
        booking = make_booking("garbage", status="reserved")
        self.assertFalse(_is_overdue_never_picked_up(booking))
