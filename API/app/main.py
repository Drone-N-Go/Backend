"""
app/main.py
-----------
Drone N' Go API — FastAPI application entrypoint.
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import admin, auth, bookings, drones, locations, users, webhooks
from app.core.config import get_settings

# Import all models so SQLAlchemy registers them with Base.metadata
from app.models import (  # noqa: F401
    admin_audit_event,
    admin_profile,
    booking,
    damage_report,
    drone,
    drone_favorite,
    locker_access_event,
    locker_location,
    locker_unit,
    login_attempt,
    maintenance_task,
    refresh_token,
    smiota_event,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)
settings = get_settings()


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
        "- **user** — standard renter, can book drones and manage their own data\n\n"
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
