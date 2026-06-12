"""
app/core/dependencies.py
------------------------
FastAPI dependency-injection callables used across routers.

  - get_current_user  → requires a valid access JWT
"""

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from dataclasses import dataclass

from app.core.admin_permissions import capabilities_for_role, role_has_capability
from app.core.security import decode_token
from app.db.session import get_db
from app.models.admin_profile import AdminProfile
from app.models.user import User


@dataclass(frozen=True)
class AdminContext:
    user: User
    profile: AdminProfile
    capabilities: set[str]
    assigned_location_ids: set[str]


async def _resolve_user_from_token(token: str, db: AsyncSession) -> User:
    """Shared logic: decode token → fetch user from DB."""
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id: str = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found.",
        )
    return user


async def get_current_user(
    access_token: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Resolve the authenticated user.
    Priority:
      1. `access_token` httponly cookie
      2. `Authorization: Bearer <token>` header
    """
    token: str | None = None

    # 1 — cookie
    if access_token:
        token = access_token

    # 2 — Authorization header
    elif authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1]

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return await _resolve_user_from_token(token, db)


async def get_optional_user(
    access_token: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    token: str | None = None
    if access_token:
        token = access_token
    elif authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1]

    if not token:
        return None

    return await _resolve_user_from_token(token, db)


async def require_admin_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AdminContext:
    result = await db.execute(
        select(AdminProfile)
        .where(AdminProfile.user_id == current_user.id, AdminProfile.status == "active")
        .options(selectinload(AdminProfile.user), selectinload(AdminProfile.location_assignments))
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Active admin access required.",
        )
    return AdminContext(
        user=current_user,
        profile=profile,
        capabilities=capabilities_for_role(profile.role),
        assigned_location_ids={assignment.location_id for assignment in profile.location_assignments},
    )


def require_capability(capability: str):
    async def checker(context: AdminContext = Depends(require_admin_profile)) -> AdminContext:
        if not role_has_capability(context.profile.role, capability):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Admin capability required: {capability}.",
            )
        return context

    return checker
