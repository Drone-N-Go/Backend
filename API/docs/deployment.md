# Deployment Guide — Render + Supabase

This API is deployed as a Render web service. Supabase provides PostgreSQL only.

## 1. Create Supabase Postgres

1. Create a Supabase project.
2. Copy the database connection string.
3. Use either the direct or pooled connection string.
4. The app accepts `postgresql://` and normalizes it to `postgresql+asyncpg://`.

## 2. Create Render Web Service

Use the repository's `render.yaml` blueprint from the Backend repo root.

Render will:

- Use `API` as the root directory.
- Run `pip install -r requirements.txt`.
- Start with `bash scripts/start.sh`.

The start script runs:

```bash
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
```

This keeps migrations compatible with Render services that do not support a separate pre-deploy command.

## 3. Environment Variables

Set these in Render:

| Variable | Description |
|---|---|
| `APP_ENV` | Use `production` |
| `DATABASE_URL` | Supabase PostgreSQL connection string |
| `JWT_SECRET` | 64+ character signing secret |
| `ADMIN_EMAIL` | Initial admin email |
| `ADMIN_PASSWORD` | Initial admin password |
| `SMIOTA_API_KEY` | Basic Auth username for Smiota webhook |
| `CORS_ORIGINS` | Comma-separated allowed origins; cannot be `*` in production |
| `AWS_ACCESS_KEY_ID` | S3 access key |
| `AWS_SECRET_ACCESS_KEY` | S3 secret |
| `AWS_REGION` | S3 region |
| `AWS_S3_BUCKET` | S3 bucket name |

## 4. Verify

After deploy:

- `GET /health`
- `GET /docs`
- `POST /api/auth/login`

If startup fails, check Render logs first. Production safety validation intentionally fails fast for placeholder secrets, short JWT secrets, or wildcard CORS.
