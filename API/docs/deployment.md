# Deployment Guide — Railway

Step-by-step instructions for deploying the Drone N' Go API to Railway.

---

## Prerequisites

- [Railway account](https://railway.app)
- GitHub repository with this codebase
- Railway CLI (optional but helpful): `npm install -g @railway/cli`

---

## Step 1 — Create a Railway Project

1. Go to [railway.app](https://railway.app) → **New Project**
2. Select **Deploy from GitHub repo**
3. Connect your GitHub account and select the `droneandgo-api` repository

---

## Step 2 — Add a PostgreSQL Database

1. In your Railway project → **New Service** → **Database** → **PostgreSQL**
2. Railway will provision a PostgreSQL instance automatically
3. Click the PostgreSQL service → **Connect** tab
4. Copy the **Database URL** — you'll need this in Step 4

---

## Step 3 — Configure the Start Command

In your Railway service settings → **Deploy** tab, set the start command to:

```
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Railway injects `$PORT` automatically.

---

## Step 4 — Set Environment Variables

In your Railway service → **Variables** tab, add every variable from `.env.example`:

| Variable | Value |
|---|---|
| `DATABASE_URL` | Paste the Railway PostgreSQL URL (change prefix to `postgresql+asyncpg://`) |
| `JWT_SECRET` | Generate a 64-char hex string |
| `ADMIN_EMAIL` | Your admin email |
| `ADMIN_PASSWORD` | Secure password |
| `SMIOTA_API_KEY` | Your Smiota API key |
| `AWS_ACCESS_KEY_ID` | From AWS IAM |
| `AWS_SECRET_ACCESS_KEY` | From AWS IAM |
| `AWS_REGION` | e.g. `us-east-1` |
| `AWS_S3_BUCKET` | Your bucket name |
| `CORS_ORIGINS` | Your production app URL(s) |
| `APP_ENV` | `production` |

---

## Step 5 — Deploy

Push to your `main` branch — Railway will automatically build and deploy.

Or trigger manually: **Deploy** → **Deploy Now**

---

## Step 6 — Verify

1. Open the Railway-provided URL (e.g. `https://droneandgo-api.up.railway.app`)
2. Visit `/health` — you should see `{"status": "healthy"}`
3. Visit `/docs` — Swagger UI should load

The API runs migrations automatically on startup, so your database tables will be created on first deploy.

---

## Updating the Deployment

Any push to `main` triggers a new Railway deploy automatically. Railway performs zero-downtime deployments.

---

## Logs

View live logs: Railway dashboard → your service → **Logs** tab.

Or via CLI:
```bash
railway logs
```
