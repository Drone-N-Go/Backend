"""
app/services/case_qr_service.py
-------------------------------
Opaque case QR token helpers shared by admin and consumer flows.
"""

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from urllib.parse import urlparse

from cryptography.fernet import Fernet
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.booking import Booking
from app.models.case_qr_token import CaseQRToken
from app.models.drone import Drone

CASE_QR_PAYLOAD_PREFIX = "https://droneandgo.io/case/"
TOKEN_PREFIX = "ck_live_"
TOKEN_BYTE_COUNT = 24


def generate_raw_case_qr_token() -> str:
    return f"{TOKEN_PREFIX}{secrets.token_urlsafe(TOKEN_BYTE_COUNT)}"


def build_case_qr_payload(raw_token: str, payload_prefix: str = CASE_QR_PAYLOAD_PREFIX) -> str:
    return f"{payload_prefix.rstrip('/')}/{raw_token}"


def extract_case_qr_token(qr_payload: str) -> str:
    value = qr_payload.strip()
    if not value:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="QR payload is required.")

    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc:
        token = parsed.path.rstrip("/").split("/")[-1]
    else:
        token = value

    token = token.strip()
    if not token or len(token) > 255 or any(ch.isspace() for ch in token):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid case QR payload.")
    return token


def hash_case_qr_token(raw_token: str) -> str:
    settings = get_settings()
    digest = hmac.new(
        settings.secret_key.encode("utf-8"),
        raw_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"hmac_sha256:{digest}"


def _fernet() -> Fernet:
    settings = get_settings()
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_case_qr_token(raw_token: str) -> str:
    return _fernet().encrypt(raw_token.encode("utf-8")).decode("utf-8")


def decrypt_case_qr_token(encrypted_token: str) -> str:
    return _fernet().decrypt(encrypted_token.encode("utf-8")).decode("utf-8")


def case_qr_payload_for_token(token: CaseQRToken) -> str:
    return build_case_qr_payload(
        decrypt_case_qr_token(token.encrypted_token),
        token.payload_prefix or CASE_QR_PAYLOAD_PREFIX,
    )


async def find_case_qr_token_by_payload(qr_payload: str, db: AsyncSession) -> CaseQRToken | None:
    raw_token = extract_case_qr_token(qr_payload)
    token_hash = hash_case_qr_token(raw_token)
    result = await db.execute(select(CaseQRToken).where(CaseQRToken.token_hash == token_hash))
    return result.scalar_one_or_none()


async def get_case_qr_token_by_payload(qr_payload: str, db: AsyncSession) -> CaseQRToken:
    token = await find_case_qr_token_by_payload(qr_payload, db)
    if not token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Case QR code is not recognized.")
    return token


async def create_pending_case_qr_token(
    drone: Drone,
    db: AsyncSession,
    *,
    admin_profile_id: str | None = None,
) -> CaseQRToken:
    raw_token = generate_raw_case_qr_token()
    token = CaseQRToken(
        drone_id=drone.id,
        token_hash=hash_case_qr_token(raw_token),
        encrypted_token=encrypt_case_qr_token(raw_token),
        payload_prefix=CASE_QR_PAYLOAD_PREFIX,
        status="pending_printed",
        created_by_admin_profile_id=admin_profile_id,
    )
    db.add(token)
    await db.flush()
    return token


async def assert_active_case_qr_matches_booking(
    booking: Booking,
    qr_payload: str,
    db: AsyncSession,
) -> CaseQRToken:
    token = await get_case_qr_token_by_payload(qr_payload, db)
    if token.status != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Case QR code is not active.")
    if token.drone_id != booking.drone_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Case QR code does not match this booking.")
    return token


def retire_case_qr_token(token: CaseQRToken, *, reason: str | None = None) -> None:
    now = datetime.now(timezone.utc)
    if token.status == "active":
        token.status = "rotated"
        token.rotated_at = now
    else:
        token.status = "voided"
        token.voided_at = now
    token.void_reason = reason
