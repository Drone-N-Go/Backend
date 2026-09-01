from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest import TestCase

from app.models.booking import Booking
from app.services.booking_service import _is_cancellable, _parse_pickup_time


def make_booking(pickup_time: str, created_at: datetime, status: str = "reserved") -> Booking:
    booking = Booking(
        user_id="user-id",
        drone_id="drone-id",
        location_id="location-id",
        pickup_time=pickup_time,
        rental_duration=4,
        rental_type="hourly",
        status=status,
        total_cost=Decimal("100.00"),
    )
    booking.created_at = created_at
    return booking


class ParsePickupTimeTests(TestCase):
    def test_parses_zulu_iso_string(self):
        parsed = _parse_pickup_time("2026-09-05T10:00:00Z")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.tzinfo, timezone.utc)

    def test_returns_none_on_garbage(self):
        self.assertIsNone(_parse_pickup_time("not-a-date"))

    def test_assumes_utc_when_no_offset_given(self):
        parsed = _parse_pickup_time("2026-09-05T10:00:00")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.utcoffset(), timedelta(0))


class IsCancellableTests(TestCase):
    def test_pickup_far_in_future_is_always_cancellable(self):
        now = datetime.now(timezone.utc)
        booking = make_booking(
            pickup_time=(now + timedelta(days=3)).isoformat(),
            created_at=now - timedelta(days=1),
        )
        self.assertTrue(_is_cancellable(booking))

    def test_pickup_just_over_24h_out_is_cancellable(self):
        now = datetime.now(timezone.utc)
        booking = make_booking(
            pickup_time=(now + timedelta(hours=24, minutes=5)).isoformat(),
            created_at=now - timedelta(hours=10),
        )
        self.assertTrue(_is_cancellable(booking))

    def test_pickup_just_under_24h_out_blocked_after_grace_period(self):
        now = datetime.now(timezone.utc)
        booking = make_booking(
            pickup_time=(now + timedelta(hours=23, minutes=55)).isoformat(),
            created_at=now - timedelta(hours=5),  # booked well over 2h ago
        )
        self.assertFalse(_is_cancellable(booking))

    def test_last_minute_booking_cancellable_within_grace_period(self):
        now = datetime.now(timezone.utc)
        booking = make_booking(
            pickup_time=(now + timedelta(hours=10)).isoformat(),  # already < 24h out
            created_at=now - timedelta(minutes=30),  # booked 30 min ago
        )
        self.assertTrue(_is_cancellable(booking))

    def test_last_minute_booking_locked_after_grace_period_expires(self):
        now = datetime.now(timezone.utc)
        booking = make_booking(
            pickup_time=(now + timedelta(hours=10)).isoformat(),  # already < 24h out
            created_at=now - timedelta(hours=3),  # booked 3h ago, grace was only 2h
        )
        self.assertFalse(_is_cancellable(booking))

    def test_pickup_in_the_past_still_evaluates_without_crashing(self):
        now = datetime.now(timezone.utc)
        booking = make_booking(
            pickup_time=(now - timedelta(hours=1)).isoformat(),
            created_at=now - timedelta(days=2),
        )
        self.assertFalse(_is_cancellable(booking))

    def test_unparseable_pickup_time_fails_open(self):
        now = datetime.now(timezone.utc)
        booking = make_booking(pickup_time="garbage", created_at=now)
        self.assertTrue(_is_cancellable(booking))
