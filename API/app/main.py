"""
app/main.py
-----------
Drone N' Go API — FastAPI application entrypoint.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import admin, auth, bookings, drones, locations, users, webhooks
from app.core.config import get_settings
from app.db.startup import ensure_database_ready

# Import all models so SQLAlchemy registers them with Base.metadata
from app.models import (  # noqa: F401
    admin_audit_event,
    admin_profile,
    booking,
    case_qr_token,
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


def _debug_log_exception(prefix: str, request: Request, exc: Exception) -> None:
    logger.error(
        "%s method=%s path=%s query=%s exc_type=%s exc=%r",
        prefix,
        request.method,
        request.url.path,
        str(request.url.query),
        type(exc).__name__,
        exc,
    )
    print(
        f"{prefix} method={request.method} path={request.url.path} "
        f"query={request.url.query!r} exc_type={type(exc).__name__} exc={exc!r}",
        flush=True,
    )
    logger.exception("%s traceback", prefix)


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


@app.exception_handler(ResponseValidationError)
async def response_validation_exception_handler(request: Request, exc: ResponseValidationError):
    _debug_log_exception("ADMIN_DEBUG_RESPONSE_VALIDATION_ERROR", request, exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
    _debug_log_exception("ADMIN_DEBUG_REQUEST_VALIDATION_ERROR", request, exc)
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    _debug_log_exception("ADMIN_DEBUG_UNHANDLED_EXCEPTION", request, exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

API_PREFIX = "/api"
app.include_router(auth.router,      prefix=API_PREFIX)
app.include_router(users.router,     prefix=API_PREFIX)
app.include_router(drones.router,    prefix=API_PREFIX)
app.include_router(locations.router, prefix=API_PREFIX)
app.include_router(bookings.router,  prefix=API_PREFIX)
app.include_router(webhooks.router,  prefix=API_PREFIX)
app.include_router(admin.router,     prefix=API_PREFIX)


@app.on_event("startup")
async def run_database_startup_checks():
    if settings.app_env == "test":
        logger.info("DB_STARTUP skipped for test environment")
        return

    logger.info("DB_STARTUP starting migration and admin schema verification")
    await ensure_database_ready()
    logger.info("DB_STARTUP completed")


@app.get("/", tags=["Health"], summary="Health check")
async def root():
    return {"service": "Drone N' Go API", "status": "online", "version": "1.0.0", "docs": "/docs"}


@app.get("/health", tags=["Health"], summary="Detailed health check")
async def health():
    return {"status": "ok", "service": "dronengo-backend"}
