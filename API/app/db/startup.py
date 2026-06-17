"""Database startup checks that must run before the API serves traffic."""

import asyncio
import logging
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

logger = logging.getLogger(__name__)

EXPECTED_ADMIN_REVISION = "20260617_0006"
EXPECTED_ADMIN_ROLE_CONSTRAINT_VALUES = {
    "owner",
    "master_developer",
    "manager",
    "developer",
    "admin",
}

REQUIRED_ADMIN_TABLES = {
    "admin_profiles",
    "admin_location_assignments",
    "admin_audit_events",
    "case_qr_tokens",
    "maintenance_tasks",
    "locker_access_events",
}

REQUIRED_ADMIN_COLUMNS = {
    "locker_units": {
        "current_drone_id",
        "smiota_locker_name",
        "smiota_unit_identifier",
        "smiota_metadata",
    },
    "case_qr_tokens": {
        "id",
        "drone_id",
        "token_hash",
        "encrypted_token",
        "payload_prefix",
        "status",
        "created_by_admin_profile_id",
        "confirmed_by_admin_profile_id",
        "confirmed_at",
        "voided_at",
        "void_reason",
        "rotated_at",
        "created_at",
        "updated_at",
    },
}


def normalize_database_url(url: str | None = None) -> str:
    normalized = url or os.environ.get("DATABASE_URL", "")
    if normalized.startswith("DATABASE_URL="):
        normalized = normalized[len("DATABASE_URL=") :]
    if normalized.startswith("postgresql://"):
        normalized = normalized.replace("postgresql://", "postgresql+asyncpg://", 1)
    if not normalized:
        raise RuntimeError("DATABASE_URL is required for database startup checks.")
    return normalized


def _api_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _alembic_config() -> Config:
    root = _api_root()
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    return config


def _run_alembic_upgrade() -> None:
    config = _alembic_config()
    logger.info("DB_STARTUP Alembic current before upgrade:")
    command.current(config)
    logger.info("DB_STARTUP running alembic upgrade head")
    command.upgrade(config, "head")
    logger.info("DB_STARTUP Alembic current after upgrade:")
    command.current(config)


async def _read_schema(connection):
    def inspect_schema(sync_connection):
        inspector = inspect(sync_connection)
        tables = set(inspector.get_table_names())
        columns = {
            table_name: {column["name"] for column in inspector.get_columns(table_name)}
            for table_name in REQUIRED_ADMIN_COLUMNS
            if table_name in tables
        }
        constraints = {
            constraint["name"]: constraint.get("sqltext", "")
            for constraint in inspector.get_check_constraints("admin_profiles")
        } if "admin_profiles" in tables else {}
        return tables, columns, constraints

    return await connection.run_sync(inspect_schema)


async def verify_admin_schema() -> None:
    engine = create_async_engine(normalize_database_url(), pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            revision = (
                await connection.execute(text("select version_num from alembic_version"))
            ).scalar_one_or_none()
            tables, columns, constraints = await _read_schema(connection)
    finally:
        await engine.dispose()

    failures: list[str] = []
    if revision != EXPECTED_ADMIN_REVISION:
        failures.append(
            f"alembic_version is {revision!r}; expected {EXPECTED_ADMIN_REVISION!r}"
        )

    missing_tables = sorted(REQUIRED_ADMIN_TABLES - tables)
    if missing_tables:
        failures.append(f"missing tables: {', '.join(missing_tables)}")

    for table_name, required_columns in REQUIRED_ADMIN_COLUMNS.items():
        existing_columns = columns.get(table_name, set())
        missing_columns = sorted(required_columns - existing_columns)
        if missing_columns:
            failures.append(f"{table_name} missing columns: {', '.join(missing_columns)}")

    role_constraint = constraints.get("ck_admin_profiles_role", "")
    missing_role_values = sorted(
        role
        for role in EXPECTED_ADMIN_ROLE_CONSTRAINT_VALUES
        if role not in role_constraint
    )
    if missing_role_values:
        failures.append(
            "ck_admin_profiles_role missing values: " + ", ".join(missing_role_values)
        )

    if failures:
        raise RuntimeError("Admin schema verification failed: " + "; ".join(failures))

    logger.info("DB_STARTUP admin schema verified at Alembic revision %s", revision)


async def ensure_database_ready() -> None:
    await asyncio.to_thread(_run_alembic_upgrade)
    await verify_admin_schema()
