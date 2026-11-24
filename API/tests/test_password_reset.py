"""Forgot-password flow against a real Postgres database (added 2026-11-24).

Needs a migrated throwaway database: set TEST_DATABASE_URL and run
`alembic upgrade head` against it first. Skipped otherwise.

Every step runs in its own session and goes through the same commit/rollback
handling as get_db(), so a counter that is only flushed before an error is
raised (and therefore rolled back) would make these tests fail.
"""

import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/droneandgo_test")
os.environ.setdefault("SECRET_KEY", "x" * 64)

from fastapi import HTTPException
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.dependencies import _resolve_user_from_token
from app.core.security import create_access_token, hash_password, verify_password
from app.models.admin_audit_event import AdminAuditEvent
from app.models.admin_profile import AdminProfile
from app.models.password_reset_code import PasswordResetCode
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.services import auth_service, password_reset_service

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")


def _async_url(url: str) -> str:
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)


@unittest.skipUnless(TEST_DATABASE_URL, "TEST_DATABASE_URL not set; skipping password reset tests")
class PasswordResetFlowTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine(_async_url(TEST_DATABASE_URL))
        self.Session = sessionmaker(bind=self.engine, class_=AsyncSession, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.execute(text(
                "TRUNCATE password_reset_codes, admin_audit_events, admin_profiles, "
                "refresh_tokens, login_attempts, users RESTART IDENTITY CASCADE"
            ))
        self.sent: list[dict] = []
        patcher = patch.object(
            password_reset_service.email_service,
            "send_password_reset_email",
            side_effect=lambda **kw: self.sent.append(kw),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def step(self, fn):
        """Run fn like a request: commit on success, roll back on any error."""
        async with self.Session() as session:
            try:
                result = await fn(session)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise

    async def make_user(self, email="ops@droneandgo.io", password="OldPassword1", admin=False,
                        must_change=False) -> User:
        async def _do(db):
            user = User(email=email, password_hash=hash_password(password),
                        first_name="Pat", last_name="Admin")
            db.add(user)
            await db.flush()
            if admin:
                db.add(AdminProfile(user_id=user.id, role="manager", must_change_password=must_change))
                await db.flush()
            return user
        return await self.step(_do)

    async def request(self, email):
        return await self.step(lambda db: password_reset_service.request_reset(email, db))

    async def confirm(self, email, code, new_password="NewPassword1"):
        return await self.step(lambda db: password_reset_service.confirm_reset(email, code, new_password, db))

    async def fetch_user(self, user_id) -> User:
        return await self.step(lambda db: db.get(User, user_id))

    def last_code(self) -> str:
        return self.sent[-1]["code"]

    @staticmethod
    def wrong(code: str) -> str:
        return f"{(int(code) + 1) % 1_000_000:06d}"

    # ------------------------------------------------------------------ #

    async def test_happy_path_resets_password(self):
        user = await self.make_user()
        msg = await self.request("OPS@droneandgo.io")
        self.assertIn("If an account exists", msg)
        self.assertEqual(len(self.sent), 1)
        self.assertRegex(self.last_code(), r"^\d{6}$")

        await self.confirm("ops@droneandgo.io", self.last_code(), "BrandNew123")
        fresh = await self.fetch_user(user.id)
        self.assertTrue(verify_password("BrandNew123", fresh.password_hash))
        self.assertIsNotNone(fresh.password_changed_at)

    async def test_code_is_stored_hashed_not_plain(self):
        await self.make_user()
        await self.request("ops@droneandgo.io")
        rows = await self.step(lambda db: db.scalars(select(PasswordResetCode)))
        rows = list(rows)
        self.assertEqual(len(rows), 1)
        self.assertNotIn(self.last_code(), rows[0].code_hash)

    async def test_unknown_email_gets_same_response_and_no_email(self):
        await self.make_user()
        msg = await self.request("nobody@example.com")
        self.assertIn("If an account exists", msg)
        self.assertEqual(self.sent, [])

    async def test_code_is_single_use(self):
        await self.make_user()
        await self.request("ops@droneandgo.io")
        code = self.last_code()
        await self.confirm("ops@droneandgo.io", code)
        with self.assertRaises(HTTPException) as ctx:
            await self.confirm("ops@droneandgo.io", code, "Another123")
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_expired_code_rejected(self):
        await self.make_user()
        await self.request("ops@droneandgo.io")
        await self.step(lambda db: db.execute(update(PasswordResetCode).values(
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))))
        with self.assertRaises(HTTPException):
            await self.confirm("ops@droneandgo.io", self.last_code())

    async def test_new_request_supersedes_old_code(self):
        await self.make_user()
        await self.request("ops@droneandgo.io")
        old = self.last_code()
        await self.request("ops@droneandgo.io")
        new = self.last_code()
        if old != new:
            with self.assertRaises(HTTPException):
                await self.confirm("ops@droneandgo.io", old)
        await self.confirm("ops@droneandgo.io", new)

    async def test_code_burned_after_max_wrong_attempts_and_counts_persist(self):
        await self.make_user()
        await self.request("ops@droneandgo.io")
        code = self.last_code()
        for _ in range(5):
            with self.assertRaises(HTTPException):
                await self.confirm("ops@droneandgo.io", self.wrong(code))
        # The right code no longer works: the 5 failures were committed, not rolled back.
        with self.assertRaises(HTTPException):
            await self.confirm("ops@droneandgo.io", code)

    async def test_daily_failure_cap_blocks_even_correct_code(self):
        await self.make_user()
        for _ in range(2):  # 2 codes x 5 wrong guesses = 10 = daily cap
            await self.request("ops@droneandgo.io")
            code = self.last_code()
            for _ in range(5):
                with self.assertRaises(HTTPException):
                    await self.confirm("ops@droneandgo.io", self.wrong(code))
        # Clear the request window so a third code can be issued.
        await self.step(lambda db: db.execute(update(PasswordResetCode).values(
            created_at=datetime.now(timezone.utc) - timedelta(hours=1))))
        await self.request("ops@droneandgo.io")
        self.assertEqual(len(self.sent), 3)
        with self.assertRaises(HTTPException):
            await self.confirm("ops@droneandgo.io", self.last_code())

    async def test_request_rate_limited_per_account(self):
        await self.make_user()
        for _ in range(5):
            msg = await self.request("ops@droneandgo.io")
            self.assertIn("If an account exists", msg)
        self.assertEqual(len(self.sent), 3)

    async def test_email_failure_does_not_leak(self):
        await self.make_user()
        with patch.object(password_reset_service.email_service, "send_password_reset_email",
                          side_effect=RuntimeError("resend down")):
            msg = await self.request("ops@droneandgo.io")
        self.assertIn("If an account exists", msg)

    async def test_reset_signs_out_everywhere(self):
        user = await self.make_user()
        login = await self.step(lambda db: auth_service.build_token_response(user, db))
        await self.request("ops@droneandgo.io")
        await self.confirm("ops@droneandgo.io", self.last_code())
        # Tokens above were issued in the same second as the reset; move the
        # reset forward so they clearly predate it, as they would in real use.
        await self.step(lambda db: db.execute(update(User).values(
            password_changed_at=datetime.now(timezone.utc) + timedelta(seconds=2))))

        tokens = await self.step(lambda db: db.scalars(select(RefreshToken)))
        self.assertTrue(all(t.revoked for t in tokens))
        with self.assertRaises(HTTPException) as ctx:
            await self.step(lambda db: _resolve_user_from_token(login.access_token, db))
        self.assertEqual(ctx.exception.status_code, 401)
        with self.assertRaises(HTTPException):
            await self.step(lambda db: auth_service.refresh_access_token(login.refresh_token, db))

    async def test_new_login_after_reset_works(self):
        user = await self.make_user()
        await self.request("ops@droneandgo.io")
        await self.confirm("ops@droneandgo.io", self.last_code())
        fresh = await self.fetch_user(user.id)
        token = create_access_token(fresh.id, fresh.email)
        resolved = await self.step(lambda db: _resolve_user_from_token(token, db))
        self.assertEqual(resolved.id, user.id)

    async def test_admin_reset_clears_forced_change_and_is_audited(self):
        user = await self.make_user(admin=True, must_change=True)
        await self.request("ops@droneandgo.io")
        await self.confirm("ops@droneandgo.io", self.last_code())
        profile = await self.step(lambda db: db.scalar(
            select(AdminProfile).where(AdminProfile.user_id == user.id)))
        self.assertFalse(profile.must_change_password)
        events = list(await self.step(lambda db: db.scalars(select(AdminAuditEvent))))
        self.assertEqual([e.action for e in events], ["admin.password_reset_via_email"])
        self.assertEqual(events[0].admin_profile_id, profile.id)

    async def test_wrong_email_with_valid_code_rejected(self):
        await self.make_user("a@droneandgo.io")
        await self.make_user("b@droneandgo.io")
        await self.request("a@droneandgo.io")
        with self.assertRaises(HTTPException):
            await self.confirm("b@droneandgo.io", self.last_code())
