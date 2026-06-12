#!/usr/bin/env python3
"""Fail fast when the deployed database is missing admin-backend schema."""

import asyncio
import os
import sys

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine


EXPECTED_REVISION = "20260612_0003"

REQUIRED_TABLES = {
    "admin_profiles",
    "admin_location_assignments",
    "admin_audit_events",
    "maintenance_tasks",
    "locker_access_events",
}

REQUIRED_COLUMNS = {
    "locker_units": {
        "current_drone_id",
        "smiota_locker_name",
        "smiota_unit_identifier",
        "smiota_metadata",
    },
}


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("DATABASE_URL="):
        url = url[len("DATABASE_URL=") :]
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if not url:
        raise RuntimeError("DATABASE_URL is required to verify the admin schema.")
    return url


async def _read_schema(connection):
    def inspect_schema(sync_connection):
        inspector = inspect(sync_connection)
        tables = set(inspector.get_table_names())
        columns = {
            table_name: {column["name"] for column in inspector.get_columns(table_name)}
            for table_name in REQUIRED_COLUMNS
            if table_name in tables
        }
        return tables, columns

    return await connection.run_sync(inspect_schema)


async def verify_admin_schema() -> None:
    engine = create_async_engine(_database_url(), pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            revision = (
                await connection.execute(text("select version_num from alembic_version"))
            ).scalar_one_or_none()
            tables, columns = await _read_schema(connection)
    finally:
        await engine.dispose()

    failures: list[str] = []
    if revision != EXPECTED_REVISION:
        failures.append(f"alembic_version is {revision!r}; expected {EXPECTED_REVISION!r}")

    missing_tables = sorted(REQUIRED_TABLES - tables)
    if missing_tables:
        failures.append(f"missing tables: {', '.join(missing_tables)}")

    for table_name, required_columns in REQUIRED_COLUMNS.items():
        existing_columns = columns.get(table_name, set())
        missing_columns = sorted(required_columns - existing_columns)
        if missing_columns:
            failures.append(f"{table_name} missing columns: {', '.join(missing_columns)}")

    if failures:
        raise RuntimeError("Admin schema verification failed: " + "; ".join(failures))

    print(f"Admin schema verified at Alembic revision {EXPECTED_REVISION}.")


def main() -> int:
    try:
        asyncio.run(verify_admin_schema())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
