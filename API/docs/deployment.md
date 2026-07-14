# Deployment Guide — Render + Supabase

This API is deployed as a Render web service. Supabase provides PostgreSQL only.
User-facing apps must keep database access routed through this backend API. Do
not add direct Supabase table access from clients unless least-privilege RLS
policies are designed and tested for those exact tables.

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

### Admin Role Update Diagnostics

If `PATCH /api/admin/staff/{profile_id}/role` returns `500` only in production, first check Render logs for `ADMIN_TRACE update_staff_role`. Then verify Supabase has the expected admin role constraint:

```sql
select conname, pg_get_constraintdef(oid)
from pg_constraint
where conrelid = 'admin_profiles'::regclass
  and conname = 'ck_admin_profiles_role';
```

Expected roles: `owner`, `master_developer`, `manager`, `developer`, and `admin`. If any are missing, deploy and run Alembic revision `20260612_0004`, which recreates the constraint. Current startup verification expects Alembic head `20260714_0009`, including public-schema Row Level Security remediation.

### Supabase Security Advisor

The `rls_disabled_in_public` finding is remediated by Alembic revision
`20260714_0009`. It dynamically enables Row Level Security for every regular or
partitioned table in the exposed `public` schema without adding `anon` policies,
broad `authenticated` policies, or `FORCE ROW LEVEL SECURITY`.

After Render deploys the backend and runs `alembic upgrade head`, rerun the
Supabase Security Advisor or verify manually:

```sql
select n.nspname as schema_name, c.relname as table_name
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public'
  and c.relkind in ('r', 'p')
  and c.relrowsecurity = false
order by 1, 2;
```

Expected result: zero rows.
