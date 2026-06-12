# Drone N' Go API

The backend REST API powering **Drone N' Go** — a drone rental platform built on FastAPI, Supabase Postgres, Render, and Smiota smart lockers.

---

## Table of Contents

- [Overview](#overview)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [Environment Variables](#environment-variables)
- [Running the API](#running-the-api)
- [API Documentation](#api-documentation)
- [Authentication](#authentication)
- [Endpoints Summary](#endpoints-summary)
- [Smiota Webhook](#smiota-webhook)
- [Image Uploads (AWS S3)](#image-uploads-aws-s3)
- [Database Migrations](#database-migrations)
- [Deployment (Render + Supabase)](#deployment-render--supabase)
- [Further Reading](#further-reading)

---

## Overview

Drone N' Go allows users to rent drones from smart locker stations on university campuses. This API handles:

- User registration and JWT authentication
- Drone inventory and availability management
- Booking lifecycle (create → checkout → return → damage review)
- Smiota locker webhook integration (passcode delivery)
- Pre/post-rental condition image uploads to AWS S3
- Admin operations for staff roles, locker access, maintenance, and audited passcode reveal

---

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | FastAPI 0.111 |
| Language | Python 3.11+ |
| Database | Supabase PostgreSQL |
| ORM | SQLAlchemy 2.0 (async) |
| Migrations | Alembic |
| Auth | JWT (PyJWT) + bcrypt |
| File Storage | AWS S3 (boto3) |
| Server | Uvicorn |

---

## Project Structure

```
API/
├── app/
│   ├── api/
│   │   └── routers/          # One file per resource group
│   │       ├── auth.py
│   │       ├── users.py
│   │       ├── drones.py
│   │       ├── locations.py
│   │       ├── bookings.py
│   │       ├── webhooks.py
│   │       └── admin.py
│   ├── core/
│   │   ├── config.py         # All settings via pydantic-settings
│   │   ├── security.py       # JWT + bcrypt
│   │   └── dependencies.py   # FastAPI auth guards
│   ├── db/
│   │   ├── base.py           # Declarative base + model imports
│   │   └── session.py        # Async engine + session factory
│   ├── models/               # SQLAlchemy ORM models
│   ├── schemas/              # Pydantic request/response schemas
│   ├── services/             # Business logic layer
│   └── main.py               # App entrypoint (startup, CORS, routers)
├── alembic/                  # Migration environment + versions
├── docs/                     # Extended developer documentation
├── .env                      # Local secrets (gitignored)
├── .env.example              # Template for other developers
├── alembic.ini
├── Makefile
└── requirements.txt
```

---

## Getting Started

### Prerequisites

- Python 3.11+
- A Supabase PostgreSQL database
- AWS S3 bucket
- Smiota API key

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/your-org/droneandgo-api.git
cd droneandgo-api/API

# 2. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate        # macOS/Linux
venv\Scripts\activate           # Windows

# 3. Install dependencies
make install
# or: pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env and fill in your credentials (see Environment Variables below)
```

---

## Environment Variables

Copy `.env.example` to `.env` for local development and fill in the required values. See [docs/environment-variables.md](docs/environment-variables.md) for a full description of optional integration variables.

| Variable | Description |
|---|---|
| `APP_ENV` | `development` locally, `production` on Render |
| `DATABASE_URL` | Supabase PostgreSQL URL |
| `SECRET_KEY` | Secret for signing JWTs |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access token lifetime in minutes |

---

## Running the API

```bash
# Development (hot reload)
make dev
# or: uvicorn app.main:app --reload --port 8000

# The API will be available at:
#   http://localhost:8000
#   http://localhost:8000/docs    ← Swagger UI
#   http://localhost:8000/redoc   ← ReDoc
```

Before first run against a real database, apply Alembic migrations:

```bash
alembic upgrade head
```

## API Documentation

Interactive documentation is available at two URLs once the server is running:

| URL | Description |
|---|---|
| `/docs` | Swagger UI — try endpoints directly in the browser |
| `/redoc` | ReDoc — clean, readable reference documentation |
| `/openapi.json` | Raw OpenAPI 3.0 schema |

---

## Authentication

The API uses JWT Bearer tokens. Tokens are issued on login and registration.

```bash
# Register
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"secret123","first_name":"Jane","last_name":"Doe"}'

# Login
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"secret123"}'

# Use the returned access_token in subsequent requests:
curl http://localhost:8000/api/auth/me \
  -H "Authorization: Bearer <access_token>"
```

Tokens are also set as `httponly` cookies for browser-based clients.

---

## Endpoints Summary

See [docs/endpoints.md](docs/endpoints.md) for the full reference.

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/api/auth/register` | None | Register a new user |
| `POST` | `/api/auth/login` | None | Login |
| `POST` | `/api/auth/logout` | None | Clear cookies |
| `GET` | `/api/auth/me` | User | Get own profile |
| `POST` | `/api/auth/refresh` | None | Refresh access token |
| `GET` | `/api/users/me/profile` | User | Get own profile |
| `PUT` | `/api/users/me/profile` | User | Update own profile |
| `GET` | `/api/drones` | Public | List drones |
| `GET` | `/api/locations` | Public | List locker locations |
| `POST` | `/api/bookings` | User | Create booking |
| `GET` | `/api/bookings` | User | List own bookings |
| `GET` | `/api/bookings/{id}/passcode` | User | Get locker passcode |
| `POST` | `/api/bookings/{id}/locker-opened` | User | Mark pickup locker opened |
| `POST` | `/api/bookings/{id}/case-verified` | User | Mark pickup QR/case verified |
| `POST` | `/api/bookings/{id}/before-photos/complete` | User | Complete pre-rental photo step |
| `POST` | `/api/bookings/{id}/start-use` | User | Start active rental use |
| `POST` | `/api/bookings/{id}/return/start` | User | Start return flow |
| `POST` | `/api/bookings/{id}/after-photos/complete` | User | Complete post-rental photo step |
| `POST` | `/api/bookings/{id}/return-locker-opened` | User | Mark return locker opened |
| `POST` | `/api/bookings/{id}/return-video` | User | Upload return video |
| `POST` | `/api/bookings/{id}/return-video/complete` | User | Complete return video step |
| `POST` | `/api/bookings/{id}/complete-return` | User | Complete return |
| `POST` | `/api/bookings/{id}/images/pre-rental` | User | Upload pre-rental images |
| `POST` | `/api/bookings/{id}/images/post-rental` | User | Upload post-rental images |
| `POST` | `/api/webhooks/smiota` | Basic Auth | Smiota locker event |
| `POST` | `/api/admin/setup/owner` | None | First Owner setup, self-disables after setup |
| `GET` | `/api/admin/me` | Admin | Get admin profile and capabilities |
| `GET` | `/api/admin/lockers/current-state` | Admin | List mapped locker state with masked passcodes |
| `POST` | `/api/admin/lockers/{id}/reveal-passcode` | Admin | Reveal passcode and write audit event |
| `PATCH` | `/api/admin/lockers/{id}/mapping` | Admin | Update Smiota locker mapping |
| `PATCH` | `/api/admin/lockers/{id}/maintenance` | Admin | Update locker maintenance status |
| `PATCH` | `/api/admin/lockers/{id}/drone` | Admin | Assign or unassign a drone from a locker |
| `GET` | `/api/admin/maintenance/tasks` | Admin | List maintenance tasks in scope |
| `POST` | `/api/admin/maintenance/tasks` | Admin | Create maintenance task |
| `GET` | `/api/admin/stats` | Admin | Role-aware stats |

---

## Smiota Webhook

See [docs/smiota-webhook.md](docs/smiota-webhook.md) for full integration details.

Smiota sends `POST` requests to `/api/webhooks/smiota` when:
- `PackageDeposited` — drone placed in locker (passcode is stored on the booking)
- `PackagePickedUp` — user picks up the drone; event is recorded without skipping app verification

Passcodes are available only through the authenticated `GET /api/bookings/{id}/passcode` endpoint.

---

## Image Uploads (AWS S3)

See [docs/aws-s3-setup.md](docs/aws-s3-setup.md) for step-by-step AWS setup instructions.

Images are stored at:
- `drone-images/pre-rental/<booking_id>/<uuid>.jpg`
- `drone-images/post-rental/<booking_id>/<uuid>.jpg`

Allowed types: JPEG, PNG, WEBP, HEIC. Max size: 20MB per file.

---

## Database Migrations

```bash
# Apply all migrations (runs automatically on startup)
make migrate

# Generate a new migration after changing a model
make revision
# You will be prompted: "Migration message: add_column_to_users"

# Roll back the last migration
make downgrade
```

---

## Deployment (Render + Supabase)

Use `Backend/API` as the Render service root directory when connecting the whole repository. If deploying from the existing `Backend/render.yaml` blueprint inside the Backend repo, its `rootDir: API` setting is equivalent.

Render build command:

```bash
pip install -r requirements.txt
```

Render start command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Set these environment variables in Render:

```env
APP_ENV=production
DATABASE_URL=<Supabase Session Pooler URL>
SECRET_KEY=<generated secret key>
ACCESS_TOKEN_EXPIRE_MINUTES=30
```

Generate `SECRET_KEY` with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```

Run migrations against Supabase before serving live traffic:

```bash
alembic upgrade head
```

See [docs/deployment.md](docs/deployment.md) for step-by-step Render + Supabase deployment instructions.

---

## Further Reading

- [docs/endpoints.md](docs/endpoints.md) — Full endpoint reference
- [docs/environment-variables.md](docs/environment-variables.md) — All env vars explained
- [docs/aws-s3-setup.md](docs/aws-s3-setup.md) — AWS S3 bucket setup
- [docs/smiota-webhook.md](docs/smiota-webhook.md) — Smiota integration guide
- [docs/deployment.md](docs/deployment.md) — Render + Supabase deployment guide
