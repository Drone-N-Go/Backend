from unittest import TestCase

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
