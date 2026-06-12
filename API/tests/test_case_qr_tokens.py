import os
from decimal import Decimal
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/dronengo_test")
os.environ.setdefault("SECRET_KEY", "x" * 64)

from app.core.dependencies import AdminContext
from app.models.admin_profile import AdminProfile
from app.models.booking import Booking
from app.models.case_qr_token import CaseQRToken
from app.models.drone import Drone
from app.services import admin_service, case_qr_service


def make_booking(drone_id: str = "drone-1", status: str = "locker_opened") -> Booking:
    return Booking(
        id="booking-1",
        user_id="user-1",
        drone_id=drone_id,
        location_id="location-1",
        pickup_time="2026-06-12T12:00:00Z",
        rental_duration=2,
        rental_type="hourly",
        status=status,
        total_cost=Decimal("50.00"),
    )


def make_drone(drone_id: str = "drone-1") -> Drone:
    return Drone(
        id=drone_id,
        model_name="DJI Mini 4 Pro",
        subtitle="Compact aerial kit",
        description="",
        category="professional",
        skill_level="intermediate",
        serial_number="DJI-M4P-001",
        status="available",
        hourly_rate=Decimal("25.00"),
        daily_rate=Decimal("120.00"),
        rating=Decimal("0"),
        review_count=0,
        image_urls=[],
        standout_features=[],
        included_items=[],
        rules=[],
        specs={},
    )


class CaseQRHelperTests(TestCase):
    def test_payload_round_trip_uses_encrypted_token_and_hmac_hash(self):
        raw_token = case_qr_service.generate_raw_case_qr_token()
        encrypted = case_qr_service.encrypt_case_qr_token(raw_token)
        token_hash = case_qr_service.hash_case_qr_token(raw_token)

        self.assertNotIn(raw_token, encrypted)
        self.assertEqual(case_qr_service.decrypt_case_qr_token(encrypted), raw_token)
        self.assertTrue(token_hash.startswith("hmac_sha256:"))

    def test_extract_accepts_url_or_raw_token(self):
        raw_token = "ck_live_abc123"
        payload = case_qr_service.build_case_qr_payload(raw_token)

        self.assertEqual(case_qr_service.extract_case_qr_token(payload), raw_token)
        self.assertEqual(case_qr_service.extract_case_qr_token(raw_token), raw_token)

    def test_retire_active_token_marks_rotated(self):
        token = CaseQRToken(drone_id="drone-1", token_hash="hash", encrypted_token="encrypted", status="active")

        case_qr_service.retire_case_qr_token(token, reason="Replace label")

        self.assertEqual(token.status, "rotated")
        self.assertIsNotNone(token.rotated_at)
        self.assertEqual(token.void_reason, "Replace label")

    def test_retire_pending_token_marks_voided(self):
        token = CaseQRToken(
            drone_id="drone-1",
            token_hash="hash",
            encrypted_token="encrypted",
            status="pending_printed",
        )

        case_qr_service.retire_case_qr_token(token, reason="Damaged")

        self.assertEqual(token.status, "voided")
        self.assertIsNotNone(token.voided_at)


class CaseQRServiceTests(IsolatedAsyncioTestCase):
    async def test_active_case_qr_must_match_booking_drone(self):
        token = CaseQRToken(
            drone_id="drone-2",
            token_hash="hash",
            encrypted_token="encrypted",
            status="active",
        )

        with patch.object(
            case_qr_service,
            "get_case_qr_token_by_payload",
            new=AsyncMock(return_value=token),
        ):
            with self.assertRaises(HTTPException) as raised:
                await case_qr_service.assert_active_case_qr_matches_booking(
                    make_booking(drone_id="drone-1"),
                    "ck_live_wrong",
                    Mock(),
                )

        self.assertEqual(raised.exception.status_code, 403)

    async def test_inactive_case_qr_is_rejected_for_booking(self):
        token = CaseQRToken(
            drone_id="drone-1",
            token_hash="hash",
            encrypted_token="encrypted",
            status="pending_printed",
        )

        with patch.object(
            case_qr_service,
            "get_case_qr_token_by_payload",
            new=AsyncMock(return_value=token),
        ):
            with self.assertRaises(HTTPException) as raised:
                await case_qr_service.assert_active_case_qr_matches_booking(
                    make_booking(drone_id="drone-1"),
                    "ck_live_pending",
                    Mock(),
                )

        self.assertEqual(raised.exception.status_code, 403)

    async def test_confirm_pending_token_activates_and_rotates_existing_active(self):
        raw_token = "ck_live_confirm"
        token = CaseQRToken(
            id="token-new",
            drone_id="drone-1",
            token_hash=case_qr_service.hash_case_qr_token(raw_token),
            encrypted_token=case_qr_service.encrypt_case_qr_token(raw_token),
            status="pending_printed",
        )
        active_token = CaseQRToken(
            id="token-old",
            drone_id="drone-1",
            token_hash="old-hash",
            encrypted_token=case_qr_service.encrypt_case_qr_token("ck_live_old"),
            status="active",
        )
        drone = make_drone("drone-1")
        db = Mock()
        db.flush = AsyncMock()
        active_result = Mock()
        active_result.scalars.return_value.all.return_value = [active_token]
        db.execute = AsyncMock(return_value=active_result)
        context = AdminContext(
            user=Mock(id="user-1"),
            profile=AdminProfile(id="admin-1", user_id="user-1", role="admin", status="active"),
            capabilities=set(),
            assigned_location_ids=set(),
        )

        with (
            patch.object(admin_service, "_get_case_qr_token", new=AsyncMock(return_value=token)),
            patch.object(admin_service, "_get_admin_drone", new=AsyncMock(return_value=drone)),
            patch.object(admin_service, "_audit", new=AsyncMock()),
        ):
            response = await admin_service.confirm_case_qr_token(
                context,
                "token-new",
                case_qr_service.build_case_qr_payload(raw_token),
                db,
            )

        self.assertEqual(token.status, "active")
        self.assertEqual(active_token.status, "rotated")
        self.assertEqual(response.token_id, "token-new")

    async def test_confirm_token_rejects_wrong_physical_label(self):
        token = CaseQRToken(
            id="token-new",
            drone_id="drone-1",
            token_hash=case_qr_service.hash_case_qr_token("ck_live_expected"),
            encrypted_token=case_qr_service.encrypt_case_qr_token("ck_live_expected"),
            status="pending_printed",
        )
        context = AdminContext(
            user=Mock(id="user-1"),
            profile=AdminProfile(id="admin-1", user_id="user-1", role="admin", status="active"),
            capabilities=set(),
            assigned_location_ids=set(),
        )

        with patch.object(admin_service, "_get_case_qr_token", new=AsyncMock(return_value=token)):
            with self.assertRaises(HTTPException) as raised:
                await admin_service.confirm_case_qr_token(
                    context,
                    "token-new",
                    "ck_live_wrong",
                    Mock(),
                )

        self.assertEqual(raised.exception.status_code, 409)
