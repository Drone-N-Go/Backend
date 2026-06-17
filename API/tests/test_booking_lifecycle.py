from decimal import Decimal
from unittest import TestCase

from fastapi import HTTPException

from app.core.booking_lifecycle import BOOKING_TRANSITIONS
from app.models.booking import Booking
from app.models.damage_report import DamageReport
from app.services.booking_service import _advance_booking_status, _assert_evidence


def make_booking(status: str) -> Booking:
    return Booking(
        user_id="user-id",
        drone_id="drone-id",
        location_id="location-id",
        pickup_time="2026-06-09T10:00:00Z",
        rental_duration=4,
        rental_type="hourly",
        status=status,
        total_cost=Decimal("100.00"),
    )


class BookingLifecycleTests(TestCase):
    def test_all_frontend_transitions_advance_and_stamp_timestamps(self):
        booking = make_booking("reserved")

        for target_status in BOOKING_TRANSITIONS:
            _advance_booking_status(booking, target_status)
            self.assertEqual(booking.status, target_status)

        self.assertIsNotNone(booking.ready_for_pickup_at)
        self.assertIsNotNone(booking.locker_opened_at)
        self.assertIsNotNone(booking.case_verified_at)
        self.assertIsNotNone(booking.before_photos_completed_at)
        self.assertIsNotNone(booking.in_use_at)
        self.assertIsNotNone(booking.return_started_at)
        self.assertIsNotNone(booking.after_photos_completed_at)
        self.assertIsNotNone(booking.return_locker_opened_at)
        self.assertIsNotNone(booking.return_video_completed_at)
        self.assertIsNotNone(booking.returned_at)

    def test_skipped_transition_raises_conflict(self):
        booking = make_booking("reserved")

        with self.assertRaises(HTTPException) as raised:
            _advance_booking_status(booking, "locker_opened")

        self.assertEqual(raised.exception.status_code, 409)

    def test_retrying_current_status_is_idempotent(self):
        booking = make_booking("case_verified")

        returned = _advance_booking_status(booking, "case_verified")

        self.assertIs(returned, booking)
        self.assertEqual(booking.status, "case_verified")

    def test_terminal_booking_cannot_advance(self):
        booking = make_booking("cancelled")

        with self.assertRaises(HTTPException) as raised:
            _advance_booking_status(booking, "locker_opened")

        self.assertEqual(raised.exception.status_code, 409)

    def test_required_evidence_is_enforced(self):
        with self.assertRaises(HTTPException) as raised:
            _assert_evidence(None, "pre_rental")

        self.assertEqual(raised.exception.status_code, 409)

    def test_evidence_check_has_no_demo_override(self):
        with self.assertRaises(HTTPException) as raised:
            _assert_evidence(None, "pre_rental")

        self.assertEqual(raised.exception.status_code, 409)

    def test_return_video_evidence_accepts_uploaded_url(self):
        report = DamageReport(
            booking_id="booking-id",
            user_id="user-id",
            drone_id="drone-id",
            pre_rental_images=[],
            post_rental_images=[],
            return_video_url="https://example.com/video.mov",
            condition_status="needs_review",
        )

        _assert_evidence(report, "return_video")
