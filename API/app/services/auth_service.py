"""
app/services/auth_service.py
-----------------------------
Business logic for authentication:
  - register, login (with brute-force protection), refresh, admin creation
"""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.login_attempt import LoginAttempt
from app.models.user import User
from app.schemas.user import (
    AdminCreateRequest,
    TokenResponse,
    UserRegisterRequest,
    UserResponse,
)

logger = logging.getLogger(__name__)
settings = get_settings()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _build_token_response(user: User) -> TokenResponse:
    access_token = create_access_token(user.id, user.email)
    refresh_token = create_refresh_token(user.id)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )


async def _get_or_create_attempt(db: AsyncSession, identifier: str) -> LoginAttempt:
    result = await db.execute(
        select(LoginAttempt).where(LoginAttempt.identifier == identifier)
    )
    attempt = result.scalar_one_or_none()
    if not attempt:
        attempt = LoginAttempt(identifier=identifier, count=0)
        db.add(attempt)
        await db.flush()
    return attempt


# --------------------------------------------------------------------------- #
# Public service functions
# --------------------------------------------------------------------------- #

async def register_user(body: UserRegisterRequest, db: AsyncSession) -> TokenResponse:
    """Register a new user account. Email must be unique."""
    existing = await db.execute(select(User).where(User.email == body.email.lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    user = User(
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        first_name=body.first_name,
        last_name=body.last_name,
        address=body.address,
        school=body.school,
        role="user",
    )
    db.add(user)
    await db.flush()
    logger.info("New user registered: %s", user.email)
    return _build_token_response(user)


async def login_user(
    email: str, password: str, request: Request, db: AsyncSession
) -> TokenResponse:
    """
    Authenticate a user.
    Enforces brute-force protection: 5 failed attempts → 15 min lockout.
    """
    client_ip = request.client.host if request.client else "unknown"
    identifier = f"{client_ip}:{email.lower()}"

    attempt = await _get_or_create_attempt(db, identifier)

    # Check lockout
    if attempt.lockout_until and attempt.lockout_until > datetime.now(timezone.utc):
        remaining = int((attempt.lockout_until - datetime.now(timezone.utc)).total_seconds() / 60)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Account locked due to too many failed attempts. Try again in {remaining} minute(s).",
        )

    # Fetch user
    result = await db.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one_or_none()

    if not user or not verify_password(password, user.password_hash):
        attempt.count += 1
        attempt.updated_at = datetime.now(timezone.utc)

        if attempt.count >= settings.max_login_attempts:
            attempt.lockout_until = datetime.now(timezone.utc) + timedelta(
                minutes=settings.lockout_minutes
            )
            await db.flush()
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many failed attempts. Account locked for {settings.lockout_minutes} minutes.",
            )

        await db.flush()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    # Success — clear attempt counter
    attempt.count = 0
    attempt.lockout_until = None
    attempt.updated_at = datetime.now(timezone.utc)
    await db.flush()

    logger.info("User logged in: %s", user.email)
    return _build_token_response(user)


async def refresh_access_token(refresh_token: str, db: AsyncSession) -> TokenResponse:
    """Exchange a valid refresh token for a new access token."""
    payload = decode_token(refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token.",
        )

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found.",
        )

    return _build_token_response(user)


async def create_admin_account(body: AdminCreateRequest, db: AsyncSession) -> User:
    """Create a new admin-role user. Only callable by existing admins."""
    existing = await db.execute(select(User).where(User.email == body.email.lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    admin = User(
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        first_name=body.first_name,
        last_name=body.last_name,
        role="admin",
    )
    db.add(admin)
    await db.flush()
    logger.info("Admin account created: %s", admin.email)
    return admin
