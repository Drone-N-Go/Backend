# Environment Variables

Full description of every environment variable used by the Drone N' Go API.

---

## DATABASE_URL

```
DATABASE_URL=YOUR_DATABASE_URL_HERE
```

Your Supabase PostgreSQL connection string. The app normalizes `postgresql://` to `postgresql+asyncpg://` automatically.

---

## SECRET_KEY

```
SECRET_KEY=YOUR_SECRET_KEY_HERE
```

A long random secret used to sign and verify JWT tokens. Generate one with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```

Never share this. Rotate it to instantly invalidate all active sessions.

---

## SMIOTA_API_KEY

```
SMIOTA_API_KEY=YOUR_SMIOTA_API_KEY_HERE
```

The API key used to authenticate incoming Smiota webhook requests. Smiota sends this as the HTTP Basic Auth username. You can generate any string — just make sure Smiota is configured to use the same value.

---

## CORS_ORIGINS

```
CORS_ORIGINS="*"
# or in production:
CORS_ORIGINS="https://app.droneandgo.io"
```

Comma-separated list of allowed CORS origins. Use `*` for development. In production, set this to your app's exact origin(s).

---

## AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY

```
AWS_ACCESS_KEY_ID=YOUR_AWS_ACCESS_KEY_ID_HERE
AWS_SECRET_ACCESS_KEY=YOUR_AWS_SECRET_ACCESS_KEY_HERE
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

The port the Uvicorn server listens on. Render sets this automatically via its own `PORT` variable.
