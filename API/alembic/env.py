"""
alembic/env.py
--------------
Alembic migration environment.
Uses the DATABASE_URL from .env and imports all models via app.db.base.
"""

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Load local .env only for local development.
from dotenv import load_dotenv

if os.environ.get("APP_ENV", "development").lower() == "development":
    load_dotenv()

# Import Base and all models so Alembic can discover them
from app.db.base import Base  # noqa: E402
from app.models.user import User                        # noqa: F401, E402
from app.models.drone import Drone                      # noqa: F401, E402
from app.models.drone_favorite import DroneFavorite     # noqa: F401, E402
from app.models.locker_location import LockerLocation   # noqa: F401, E402
from app.models.locker_unit import LockerUnit           # noqa: F401, E402
from app.models.booking import Booking                  # noqa: F401, E402
from app.models.damage_report import DamageReport       # noqa: F401, E402
from app.models.smiota_event import SmiotaEvent         # noqa: F401, E402
from app.models.login_attempt import LoginAttempt       # noqa: F401, E402
from app.models.refresh_token import RefreshToken       # noqa: F401, E402
from app.models.admin_profile import AdminLocationAssignment, AdminProfile  # noqa: F401, E402
from app.models.admin_audit_event import AdminAuditEvent  # noqa: F401, E402
from app.models.locker_access_event import LockerAccessEvent  # noqa: F401, E402
from app.models.maintenance_task import MaintenanceTask  # noqa: F401, E402

config = context.config

# Override sqlalchemy.url with the real DATABASE_URL from env
database_url = os.environ.get("DATABASE_URL", "")
if not database_url:
    raise RuntimeError("DATABASE_URL is required to run Alembic migrations.")
if database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
config.set_main_option("sqlalchemy.url", database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
