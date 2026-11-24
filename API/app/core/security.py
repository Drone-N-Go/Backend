"""
app/core/security.py
--------------------
JWT token creation and verification.
Password hashing and verification via bcrypt.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt

from app.core.config import get_settings

settings = get_settings()


# --------------------------------------------------------------------------- #
# Password hashing
# --------------------------------------------------------------------------- #

def hash_password(plain: str) -> str:
    """Hash a plain-text password using bcrypt."""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(plain.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if plain matches the bcrypt hash."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# --------------------------------------------------------------------------- #
# JWT tokens
# --------------------------------------------------------------------------- #

def _create_token(payload: dict, expires_delta: timedelta) -> str:
    """Internal helper — sign a JWT with expiry."""
    now = datetime.now(timezone.utc)
    expire = now + expires_delta
    # iat lets the API reject tokens issued before a password reset.
    to_encode = {**payload, "iat": int(now.timestamp()), "exp": expire}
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: str, email: str) -> str:
    """Create a short-lived access token (30 min)."""
    return _create_token(
        {"sub": user_id, "email": email, "type": "access"},
        timedelta(minutes=settings.access_token_expire_minutes),
    )


def create_refresh_token(user_id: str) -> str:
    """Create a long-lived refresh token (7 days)."""
    return _create_token(
        {"sub": user_id, "type": "refresh"},
        timedelta(days=settings.refresh_token_expire_days),
    )


def decode_token(token: str) -> Optional[dict]:
    """
    Decode and verify a JWT.
    Returns the payload dict on success, None on any error.
    """
    try:
        return jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def token_predates_password_change(payload: dict, password_changed_at: datetime | None) -> bool:
    """True if this token was issued before the user's last password reset.

    Compared at whole-second precision (JWT iat is in seconds). Tokens without
    iat predate this check; they are rejected only for users who have reset.
    """
    if password_changed_at is None:
        return False
    if password_changed_at.tzinfo is None:
        password_changed_at = password_changed_at.replace(tzinfo=timezone.utc)
    iat = payload.get("iat")
    if not isinstance(iat, (int, float)):
        return True
    return int(iat) < int(password_changed_at.timestamp())
