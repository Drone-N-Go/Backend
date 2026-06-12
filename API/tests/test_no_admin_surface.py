import os
from unittest import TestCase

from fastapi import HTTPException

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/dronengo_test")
os.environ.setdefault("SECRET_KEY", "x" * 64)

from app.main import app  # noqa: E402
from app.models.booking import Booking  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.booking_service import _assert_current_user_booking  # noqa: E402


class AdminSurfaceTests(TestCase):
    def test_legacy_admin_routes_are_not_registered(self):
        route_paths = {
            getattr(route, "path", None)
            for route in app.routes
            if getattr(route, "path", None)
        }
        route_methods = {
            (method, route.path)
            for route in app.routes
            for method in getattr(route, "methods", set())
        }

        self.assertNotIn("/api/admin/analytics", route_paths)
        self.assertNotIn("/api/admin/drones/{drone_id}/condition", route_paths)
        self.assertNotIn("/api/auth/create-admin", route_paths)
        self.assertNotIn("/api/bookings/{booking_id}/smiota-link", route_paths)
        self.assertNotIn("/api/bookings/{booking_id}/status", route_paths)
        self.assertNotIn(("GET", "/api/users"), route_methods)
        self.assertNotIn(("POST", "/api/drones"), route_methods)
        self.assertNotIn(("PUT", "/api/drones/{drone_id}"), route_methods)
        self.assertNotIn(("DELETE", "/api/drones/{drone_id}"), route_methods)
        self.assertNotIn(("PATCH", "/api/drones/{drone_id}/status"), route_methods)
        self.assertNotIn(("POST", "/api/locations"), route_methods)
        self.assertNotIn(("PUT", "/api/locations/{location_id}"), route_methods)
        self.assertNotIn(("DELETE", "/api/locations/{location_id}"), route_methods)
        self.assertNotIn(("POST", "/api/locations/{location_id}/units"), route_methods)
        self.assertNotIn(("PUT", "/api/locations/{location_id}/units/{unit_id}"), route_methods)
        self.assertNotIn(("DELETE", "/api/locations/{location_id}/units/{unit_id}"), route_methods)

    def test_admin_foundation_routes_are_registered(self):
        route_methods = {
            (method, route.path)
            for route in app.routes
            for method in getattr(route, "methods", set())
        }

        self.assertIn(("POST", "/api/admin/setup/owner"), route_methods)
        self.assertIn(("GET", "/api/admin/me"), route_methods)
        self.assertIn(("PATCH", "/api/admin/staff/{profile_id}/role"), route_methods)
        self.assertIn(("GET", "/api/admin/lockers/current-state"), route_methods)
        self.assertIn(("POST", "/api/admin/lockers/{locker_unit_id}/reveal-passcode"), route_methods)
        self.assertIn(("PATCH", "/api/admin/lockers/{locker_unit_id}/mapping"), route_methods)

    def test_admin_role_no_longer_bypasses_booking_ownership(self):
        booking = Booking(user_id="booking-user", drone_id="drone-id", location_id="location-id")
        user = User(
            id="other-user",
            email="admin@example.com",
            password_hash="hash",
            first_name="Admin",
            last_name="User",
            role="admin",
        )

        with self.assertRaises(HTTPException) as raised:
            _assert_current_user_booking(booking, user)

        self.assertEqual(raised.exception.status_code, 403)

    def test_booking_owner_still_has_access(self):
        booking = Booking(user_id="booking-user", drone_id="drone-id", location_id="location-id")
        user = User(
            id="booking-user",
            email="user@example.com",
            password_hash="hash",
            first_name="Regular",
            last_name="User",
            role="user",
        )

        _assert_current_user_booking(booking, user)
