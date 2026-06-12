import os
from datetime import datetime, timezone
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/dronengo_test")
os.environ.setdefault("SECRET_KEY", "x" * 64)

from app.core.admin_permissions import (
    DEVELOPER,
    MANAGER,
    MASTER_DEVELOPER,
    OWNER,
    ADMIN,
    MANAGE_OWNER_ACCOUNTS,
    VIEW_LOCKER_STATE,
    VIEW_MONEY,
    can_manage_target_role,
    role_has_capability,
)
from app.core.dependencies import AdminContext
from app.models.admin_profile import AdminProfile
from app.schemas.admin import LockerCurrentStateResponse
from app.services import admin_service


class AdminPermissionTests(TestCase):
    def test_owner_and_master_developer_have_money_and_owner_management(self):
        for role in (OWNER, MASTER_DEVELOPER):
            self.assertTrue(role_has_capability(role, VIEW_MONEY))
            self.assertTrue(role_has_capability(role, MANAGE_OWNER_ACCOUNTS))
            self.assertTrue(can_manage_target_role(role, OWNER))

    def test_manager_can_view_money_but_not_manage_owner_accounts(self):
        self.assertTrue(role_has_capability(MANAGER, VIEW_MONEY))
        self.assertFalse(role_has_capability(MANAGER, MANAGE_OWNER_ACCOUNTS))
        self.assertFalse(can_manage_target_role(MANAGER, OWNER))
        self.assertFalse(can_manage_target_role(MANAGER, MASTER_DEVELOPER))

    def test_developer_cannot_view_money_or_manage_owner_accounts(self):
        self.assertFalse(role_has_capability(DEVELOPER, VIEW_MONEY))
        self.assertFalse(role_has_capability(DEVELOPER, MANAGE_OWNER_ACCOUNTS))
        self.assertFalse(can_manage_target_role(DEVELOPER, OWNER))
        self.assertFalse(can_manage_target_role(DEVELOPER, MASTER_DEVELOPER))

    def test_admin_has_locker_state_but_not_money(self):
        self.assertTrue(role_has_capability(ADMIN, VIEW_LOCKER_STATE))
        self.assertFalse(role_has_capability(ADMIN, VIEW_MONEY))

    def test_locker_current_state_keeps_ios_id_field(self):
        response = LockerCurrentStateResponse(
            id="locker-1",
            locker_unit_id="locker-1",
            location_id="location-1",
            location_name="DNG Headquarters",
            unit_number="A1",
            status="available",
            smiota_locker_name=None,
            smiota_unit_identifier=None,
            has_current_passcode=False,
            passcode_mask=None,
            latest_tracking_id=None,
            latest_event=None,
            assigned_drone=None,
            active_booking=None,
            maintenance_task_count=0,
        )

        payload = response.model_dump(mode="json")
        self.assertEqual(payload["id"], "locker-1")
        self.assertEqual(payload["locker_unit_id"], "locker-1")


class AdminRoleUpdateServiceTests(IsolatedAsyncioTestCase):
    def _profile(self, profile_id: str, role: str) -> AdminProfile:
        now = datetime.now(timezone.utc)
        return AdminProfile(
            id=profile_id,
            user_id=f"user-{profile_id}",
            role=role,
            status="active",
            title=None,
            phone=None,
            notes=None,
            created_at=now,
            updated_at=now,
        )

    async def test_owner_can_change_owner_to_master_developer(self):
        actor = self._profile("actor-profile", OWNER)
        target = self._profile("target-profile", OWNER)
        db = Mock()
        db.flush = AsyncMock()
        context = AdminContext(
            user=Mock(id="actor-user"),
            profile=actor,
            capabilities=set(),
            assigned_location_ids=set(),
        )

        with (
            patch.object(admin_service, "_get_admin_profile", new=AsyncMock(return_value=target)) as get_profile,
            patch.object(admin_service, "_assigned_location_ids", new=AsyncMock(return_value=[])) as assigned_locations,
            patch.object(admin_service, "_audit", new=AsyncMock()) as audit,
        ):
            response = await admin_service.update_staff_role(
                context,
                "target-profile",
                MASTER_DEVELOPER,
                db,
            )

        self.assertEqual(get_profile.await_count, 2)
        get_profile.assert_awaited_with("target-profile", db)
        assigned_locations.assert_awaited_once_with("target-profile", db)
        db.add.assert_called_once_with(target)
        db.flush.assert_awaited_once()
        audit.assert_awaited_once()
        self.assertEqual(target.role, MASTER_DEVELOPER)
        self.assertEqual(response.role, MASTER_DEVELOPER)

    async def test_manager_cannot_assign_master_developer(self):
        actor = self._profile("actor-profile", MANAGER)
        target = self._profile("target-profile", ADMIN)
        db = Mock()
        db.flush = AsyncMock()
        context = AdminContext(
            user=Mock(id="actor-user"),
            profile=actor,
            capabilities=set(),
            assigned_location_ids=set(),
        )

        with patch.object(admin_service, "_get_admin_profile", new=AsyncMock(return_value=target)):
            with self.assertRaises(HTTPException) as raised:
                await admin_service.update_staff_role(
                    context,
                    "target-profile",
                    MASTER_DEVELOPER,
                    db,
                )

        self.assertEqual(raised.exception.status_code, 403)
        db.add.assert_not_called()
        db.flush.assert_not_awaited()
