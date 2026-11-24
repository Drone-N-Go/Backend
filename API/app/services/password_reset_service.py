"""
app/services/password_reset_service.py
--------------------------------------
Forgot-password flow (added 2026-11-24), shared by every client:
Admin iOS, Admin Android, the web admin portal and the consumer apps.

  1. request_reset(email)          -> emails a 6-digit code if the account exists
  2. confirm_reset(email, code, pw) -> sets the new password

Security properties:
  - No account enumeration: request always returns the same response, and
    every confirm failure returns the same message.
  - Codes are stored only as an HMAC (SECRET_KEY, bound to the user id).
  - Single use; expire after a few minutes; a new request supersedes older codes.
  - Brute force is capped PER ACCOUNT, not per IP. Behind Render's proxy the
    API may see every client as the same IP, so a per-IP lockout could lock
    out everyone at once.
  - Success revokes every refresh token and, via users.password_changed_at,
    every access token issued before the reset: the account is signed out
    on all devices.
  - Admin resets clear must_change_password (the admin just chose their own
    password) and are written to admin_audit_events.

Failure counters are COMMITTED before the error is raised. get_db() rolls
back on any exception, so a counter that was only flushed would be undone
(the bug that currently disables login lockout in auth_service.login_user).
"""

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.admin_audit_event import AdminAuditEvent
from app.models.admin_profile import AdminProfile
from app.models.login_attempt import LoginAttempt
from app.models.password_reset_code import PasswordResetCode
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.services import email_service

logger = logging.getLogger(__name__)
settings = get_settings()

REQUEST_ACCEPTED_MESSAGE = (
    "If an account exists for that email, we've sent a 6-digit reset code. "
    "It expires in {ttl} minutes."
)
INVALID_CODE_DETAIL = "That code is invalid or has expired. Request a new code and try again."
RESET_SUCCESS_MESSAGE = "Your password has been reset. Sign in with your new password."


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _hash_code(user_id: str, code: str) -> str:
    return hmac.new(
        settings.secret_key.encode("utf-8"),
        f"password-reset:{user_id}:{code}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


async def _find_user(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email.lower().strip()))
    return result.scalar_one_or_none()


async def _daily_failure_counter(db: AsyncSession, user_id: str) -> LoginAttempt:
    identifier = f"password-reset-failures:{user_id}"
    result = await db.execute(select(LoginAttempt).where(LoginAttempt.identifier == identifier))
    counter = result.scalar_one_or_none()
    if counter is None:
        counter = LoginAttempt(identifier=identifier, count=0)
        db.add(counter)
        await db.flush()
    elif counter.updated_at and _aware(counter.updated_at) < _now() - timedelta(days=1) and not (
        counter.lockout_until and _aware(counter.lockout_until) > _now()
    ):
        # Rolling day has passed since the last failure: start fresh.
        counter.count = 0
        counter.lockout_until = None
    return counter


async def _fail(db: AsyncSession) -> None:
    """Persist any counters touched so far, then reject with the generic message."""
    await db.commit()
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=INVALID_CODE_DETAIL)


# --------------------------------------------------------------------------- #
# Step 1: request a code
# --------------------------------------------------------------------------- #

async def request_reset(email: str, db: AsyncSession) -> str:
    """Email a reset code if the account exists. Always returns the same message."""
    accepted = REQUEST_ACCEPTED_MESSAGE.format(ttl=settings.password_reset_code_ttl_minutes)

    user = await _find_user(db, email)
    if user is None:
        logger.info("password reset requested for unknown email")
        return accepted

    window_start = _now() - timedelta(minutes=settings.password_reset_request_window_minutes)
    recent = await db.scalar(
        select(func.count(PasswordResetCode.id)).where(
            PasswordResetCode.user_id == user.id,
            PasswordResetCode.created_at >= window_start,
        )
    )
    if (recent or 0) >= settings.password_reset_max_requests_per_window:
        # Silently drop: stops inbox flooding without revealing the account exists.
        logger.warning("password reset request rate-limited user_id=%s", user.id)
        return accepted

    # A new code supersedes any outstanding ones.
    await db.execute(
        update(PasswordResetCode)
        .where(PasswordResetCode.user_id == user.id, PasswordResetCode.used_at.is_(None))
        .values(used_at=_now())
    )

    code = _generate_code()
    db.add(
        PasswordResetCode(
            user_id=user.id,
            code_hash=_hash_code(user.id, code),
            expires_at=_now() + timedelta(minutes=settings.password_reset_code_ttl_minutes),
        )
    )
    await db.flush()

    try:
        email_service.send_password_reset_email(
            to_email=user.email,
            first_name=user.first_name,
            code=code,
            ttl_minutes=settings.password_reset_code_ttl_minutes,
        )
        logger.info("password reset code sent user_id=%s", user.id)
    except Exception:
        # Never surface delivery failures: that would reveal the account exists.
        logger.exception("failed to send password reset email user_id=%s", user.id)

    return accepted


# --------------------------------------------------------------------------- #
# Step 2: confirm with code + new password
# --------------------------------------------------------------------------- #

async def confirm_reset(email: str, code: str, new_password: str, db: AsyncSession) -> str:
    user = await _find_user(db, email)
    if user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=INVALID_CODE_DETAIL)

    counter = await _daily_failure_counter(db, user.id)
    if counter.lockout_until and _aware(counter.lockout_until) > _now():
        logger.warning("password reset confirm blocked by daily cap user_id=%s", user.id)
        await _fail(db)

    result = await db.execute(
        select(PasswordResetCode)
        .where(
            PasswordResetCode.user_id == user.id,
            PasswordResetCode.used_at.is_(None),
            PasswordResetCode.expires_at > _now(),
        )
        .order_by(PasswordResetCode.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    record = result.scalar_one_or_none()

    if record is None:
        await _fail(db)

    if not hmac.compare_digest(record.code_hash, _hash_code(user.id, code)):
        record.attempts += 1
        if record.attempts >= settings.password_reset_max_code_attempts:
            record.used_at = _now()  # burn it
        counter.count += 1
        counter.updated_at = _now()
        if counter.count >= settings.password_reset_max_daily_failures:
            counter.lockout_until = _now() + timedelta(days=1)
        logger.warning(
            "password reset wrong code user_id=%s code_attempts=%d daily_failures=%d",
            user.id, record.attempts, counter.count,
        )
        await _fail(db)

    # ---- Success ---------------------------------------------------------- #
    now = _now()
    record.used_at = now
    user.password_hash = hash_password(new_password)
    user.password_changed_at = now
    counter.count = 0
    counter.lockout_until = None

    # Sign out every existing session.
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked.is_(False))
        .values(revoked=True, revoked_at=now)
    )

    profile = await db.scalar(select(AdminProfile).where(AdminProfile.user_id == user.id))
    if profile is not None:
        profile.must_change_password = False
        db.add(
            AdminAuditEvent(
                admin_profile_id=profile.id,
                action="admin.password_reset_via_email",
                resource_type="user",
                resource_id=user.id,
                details={},
            )
        )

    await db.flush()
    logger.info("password reset completed user_id=%s admin=%s", user.id, profile is not None)
    return RESET_SUCCESS_MESSAGE
