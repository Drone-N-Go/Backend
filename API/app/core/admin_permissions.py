"""
app/core/admin_permissions.py
-----------------------------
Role-to-capability policy for the admin backend.
"""

from typing import Final


OWNER = "owner"
MASTER_DEVELOPER = "master_developer"
MANAGER = "manager"
DEVELOPER = "developer"
ADMIN = "admin"

ADMIN_ROLES: Final[set[str]] = {OWNER, MASTER_DEVELOPER, MANAGER, DEVELOPER, ADMIN}

VIEW_MONEY = "view_money"
VIEW_PLATFORM_STATS = "view_platform_stats"
MANAGE_STAFF = "manage_staff"
MANAGE_OWNER_ACCOUNTS = "manage_owner_accounts"
MANAGE_LOCATIONS = "manage_locations"
MANAGE_LOCKERS = "manage_lockers"
MANAGE_DRONES = "manage_drones"
VIEW_ALL_USERS = "view_all_users"
SUPPORT_USER_ISSUE = "support_user_issue"
VIEW_LOCKER_STATE = "view_locker_state"
REVEAL_LOCKER_PASSCODE = "reveal_locker_passcode"
CREATE_MAINTENANCE_TASK = "create_maintenance_task"
RESOLVE_MAINTENANCE_TASK = "resolve_maintenance_task"
VIEW_AUDIT_LOG = "view_audit_log"

ALL_CAPABILITIES: Final[set[str]] = {
    VIEW_MONEY,
    VIEW_PLATFORM_STATS,
    MANAGE_STAFF,
    MANAGE_OWNER_ACCOUNTS,
    MANAGE_LOCATIONS,
    MANAGE_LOCKERS,
    MANAGE_DRONES,
    VIEW_ALL_USERS,
    SUPPORT_USER_ISSUE,
    VIEW_LOCKER_STATE,
    REVEAL_LOCKER_PASSCODE,
    CREATE_MAINTENANCE_TASK,
    RESOLVE_MAINTENANCE_TASK,
    VIEW_AUDIT_LOG,
}

OWNER_EQUIVALENT_CAPABILITIES: Final[set[str]] = set(ALL_CAPABILITIES)

MANAGER_CAPABILITIES: Final[set[str]] = ALL_CAPABILITIES - {MANAGE_OWNER_ACCOUNTS}

DEVELOPER_CAPABILITIES: Final[set[str]] = ALL_CAPABILITIES - {
    VIEW_MONEY,
    MANAGE_OWNER_ACCOUNTS,
}

ADMIN_CAPABILITIES: Final[set[str]] = {
    MANAGE_LOCKERS,
    MANAGE_DRONES,
    SUPPORT_USER_ISSUE,
    VIEW_LOCKER_STATE,
    REVEAL_LOCKER_PASSCODE,
    CREATE_MAINTENANCE_TASK,
    RESOLVE_MAINTENANCE_TASK,
}

ROLE_CAPABILITIES: Final[dict[str, set[str]]] = {
    OWNER: OWNER_EQUIVALENT_CAPABILITIES,
    MASTER_DEVELOPER: OWNER_EQUIVALENT_CAPABILITIES,
    MANAGER: MANAGER_CAPABILITIES,
    DEVELOPER: DEVELOPER_CAPABILITIES,
    ADMIN: ADMIN_CAPABILITIES,
}

GLOBAL_SCOPE_ROLES: Final[set[str]] = {OWNER, MASTER_DEVELOPER, MANAGER, DEVELOPER}


def capabilities_for_role(role: str) -> set[str]:
    return set(ROLE_CAPABILITIES.get(role, set()))


def role_has_capability(role: str, capability: str) -> bool:
    return capability in ROLE_CAPABILITIES.get(role, set())


def has_global_location_scope(role: str) -> bool:
    return role in GLOBAL_SCOPE_ROLES


PROTECTED_STAFF_ROLES: Final[set[str]] = {OWNER, MASTER_DEVELOPER}


def can_manage_target_role(actor_role: str, target_role: str) -> bool:
    if target_role in PROTECTED_STAFF_ROLES and not role_has_capability(actor_role, MANAGE_OWNER_ACCOUNTS):
        return False
    return role_has_capability(actor_role, MANAGE_STAFF)
