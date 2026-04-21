# Environment Variables

Full description of every environment variable used by the Drone N' Go API.

---

## DATABASE_URL

```
DATABASE_URL="postgresql+asyncpg://USER:PASSWORD@HOST.railway.app:PORT/railway"
```

Your Railway PostgreSQL connection string. **Important:** the prefix must be `postgresql+asyncpg://` (not `postgresql://`) because the API uses async SQLAlchemy.

To find this in Railway: open your PostgreSQL service → **Connect** tab → copy the URL → replace the prefix.

---

## JWT_SECRET

```
JWT_SECRET="a7f3b2c8..."
```

A long random secret used to sign and verify JWT tokens. Generate one with:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Never share this. Rotate it to instantly invalidate all active sessions.

---

## ADMIN_EMAIL / ADMIN_PASSWORD

```
ADMIN_EMAIL="james@droneandgo.io"
ADMIN_PASSWORD="YourSecurePassword"
```

Credentials for the seed admin account, created automatically on first startup.

---

## SMIOTA_API_KEY

```
SMIOTA_API_KEY="sk_smiota_dronengo_..."
```

The API key used to authenticate incoming Smiota webhook requests. Smiota sends this as the HTTP Basic Auth username. You can generate any string — just make sure Smiota is configured to use the same value.

---

## CORS_ORIGINS

```
CORS_ORIGINS="*"
# or in production:
CORS_ORIGINS="https://app.droneandgo.io,https://admin.droneandgo.io"
```

Comma-separated list of allowed CORS origins. Use `*` for development. In production, set this to your app's exact origin(s).

---

## AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY

```
AWS_ACCESS_KEY_ID="AKIA..."
AWS_SECRET_ACCESS_KEY="abc123..."
```

IAM credentials for uploading drone images to S3. See [aws-s3-setup.md](aws-s3-setup.md) for how to create these.

---

## AWS_REGION

```
AWS_REGION="us-east-1"
```

The AWS region where your S3 bucket lives.

---

## AWS_S3_BUCKET

```
AWS_S3_BUCKET="droneandgo-images"
```

The name of your S3 bucket. Must match exactly.

---

## APP_ENV

```
APP_ENV="development"   # or: production
```

Controls SQL query logging (enabled in development, disabled in production) and other environment-specific behavior.

---

## PORT

```
PORT=8000
```

The port the Uvicorn server listens on. Railway sets this automatically via its own `PORT` variable.
