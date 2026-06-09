"""
app/main.py
-----------
Drone N' Go API — FastAPI application entrypoint.

On startup:
  1. Assumes Alembic migrations have already run
  2. Seeds the admin account if it does not exist
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.api.routers import admin, auth, bookings, drones, locations, users, webhooks
from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.user import User

# Import all models so SQLAlchemy registers them with Base.metadata
from app.models import (  # noqa: F401
    booking,
    damage_report,
    drone,
    drone_favorite,
    locker_location,
    locker_unit,
    login_attempt,
    refresh_token,
    smiota_event,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)
settings = get_settings()


async def _seed_admin() -> None:
    """Create the initial admin account if it does not yet exist."""
    if not settings.admin_email or not settings.admin_password:
        logger.info("Admin seed skipped; ADMIN_EMAIL and ADMIN_PASSWORD are not both set.")
        return

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(User).where(User.email == settings.admin_email)
            )
            if result.scalar_one_or_none():
                logger.info("Admin account already exists — skipping seed.")
                return

            admin_user = User(
                email=settings.admin_email,
                password_hash=hash_password(settings.admin_password),
                first_name="Admin",
                last_name="DroneNGo",
                role="admin",
            )
            db.add(admin_user)
            await db.commit()
            logger.info("✅  Admin account seeded: %s", settings.admin_email)
    except Exception as e:
        logger.error("❌  Admin seed failed: %s", e)
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀  Drone N' Go API starting up...")
    await _seed_admin()
    yield
    logger.info("🛑  Drone N' Go API shutting down.")


app = FastAPI(
    title="Drone N' Go API",
    description=(
        "The backend API powering **Drone N' Go** — a drone rental platform using "
        "Smiota smart lockers. \n\n"
        "## Authentication\n"
        "Most endpoints require a valid JWT. Obtain tokens via `POST /api/auth/login`. "
        "Pass the token as an `Authorization: Bearer <token>` header or via the "
        "`access_token` httponly cookie.\n\n"
        "## Roles\n"
        "- **user** — standard renter, can book drones and manage their own data\n"
        "- **admin** — full access, including drone management, analytics, and condition review\n\n"
        "## Smiota Webhook\n"
        "Smiota posts locker events to `POST /api/webhooks/smiota` using HTTP Basic Auth "
        "(API key as username, empty password)."
    ),
    version="1.0.0",
    contact={"name": "Drone N' Go", "email": "james@droneandgo.io"},
    license_info={"name": "Proprietary"},
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_PREFIX = "/api"
app.include_router(auth.router,      prefix=API_PREFIX)
app.include_router(users.router,     prefix=API_PREFIX)
app.include_router(drones.router,    prefix=API_PREFIX)
app.include_router(locations.router, prefix=API_PREFIX)
app.include_router(bookings.router,  prefix=API_PREFIX)
app.include_router(webhooks.router,  prefix=API_PREFIX)
app.include_router(admin.router,     prefix=API_PREFIX)


@app.get("/", tags=["Health"], summary="Health check")
async def root():
    return {"service": "Drone N' Go API", "status": "online", "version": "1.0.0", "docs": "/docs"}


@app.get("/health", tags=["Health"], summary="Detailed health check")
async def health():
    return {"status": "ok", "service": "dronengo-backend"}
