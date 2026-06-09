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
- Start with `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.

Run migrations against Supabase before serving live traffic:

```bash
alembic upgrade head
```

## 3. Environment Variables

Set these in Render:

| Variable | Description |
|---|---|
| `APP_ENV` | Use `production` |
| `DATABASE_URL` | Supabase Session Pooler URL |
| `SECRET_KEY` | Generated JWT signing secret |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Use `30` |

Generate `SECRET_KEY` with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```

Optional integration variables:

| Variable | Description |
|---|---|
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | Initial admin seed account |
| `SMIOTA_API_KEY` | Basic Auth username for Smiota webhook |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | S3 upload credentials |
| `AWS_REGION` | S3 region |
| `AWS_S3_BUCKET` | S3 bucket name |

## 4. Verify

After deploy:

- `GET /health`
- `GET /docs`
- `POST /api/auth/login`

If startup fails, check Render logs first. Production safety validation intentionally fails fast for missing core env vars, placeholder secrets, or short `SECRET_KEY` values.
