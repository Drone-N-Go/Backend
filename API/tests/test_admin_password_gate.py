import os
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/droneandgo_test")
os.environ.setdefault("SECRET_KEY", "x" * 64)

from app.core import dependencies
from app.core.dependencies import (
    PASSWORD_CHANGE_REQUIRED_DETAIL,
    AdminContext,
    enforce_password_changed,
    require_admin_profile,
    require_admin_profile_allow_pending_password,
)


def _profile(must_change: bool):
    p = Mock()
    p.role = "owner"
    p.must_change_password = must_change
    p.location_assignments = []
    return p


def _context(profile):
    return AdminContext(user=Mock(), profile=profile, capabilities=set(), assigned_location_ids=set())


class EnforcePasswordChangedTests(TestCase):
    def test_blocks_when_flag_set(self):
        with self.assertRaises(HTTPException) as ctx:
            enforce_password_changed(_profile(True))
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail, PASSWORD_CHANGE_REQUIRED_DETAIL)

    def test_allows_when_flag_clear(self):
        enforce_password_changed(_profile(False))  # no raise


class AdminDependencyGateTests(IsolatedAsyncioTestCase):
    async def test_require_admin_profile_blocks_pending_password(self):
        with patch.object(dependencies, "_load_admin_context", AsyncMock(return_value=_context(_profile(True)))):
            with self.assertRaises(HTTPException) as ctx:
                await require_admin_profile(current_user=Mock(), db=Mock())
        self.assertEqual(ctx.exception.detail, PASSWORD_CHANGE_REQUIRED_DETAIL)

    async def test_require_admin_profile_passes_after_change(self):
        context = _context(_profile(False))
        with patch.object(dependencies, "_load_admin_context", AsyncMock(return_value=context)):
            self.assertIs(await require_admin_profile(current_user=Mock(), db=Mock()), context)

    async def test_admin_me_dependency_is_not_gated(self):
        context = _context(_profile(True))
        with patch.object(dependencies, "_load_admin_context", AsyncMock(return_value=context)):
            self.assertIs(await require_admin_profile_allow_pending_password(current_user=Mock(), db=Mock()), context)


class AdminRouteWiringTests(TestCase):
    def test_only_admin_me_uses_ungated_dependency(self):
        from app.api.routers import admin as admin_router

        ungated = []
        for route in admin_router.router.routes:
            deps = [d.call for d in route.dependant.dependencies]
            if require_admin_profile_allow_pending_password in deps:
                ungated.append(route.path)
        self.assertEqual([p for p in ungated if p.endswith("/me")], ungated)
        self.assertEqual(len(ungated), 1)
