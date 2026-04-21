"""
app/core/dependencies.py
------------------------
FastAPI dependency-injection callables used across routers.

  - get_current_user  → requires a valid access JWT
  - require_admin     → requires valid JWT AND role == "admin"
"""

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import User


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


async def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """Extend get_current_user — additionally requires role == 'admin'."""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator privileges required.",
        )
    return current_user
