# AWS S3 Setup Guide

Step-by-step instructions to configure an AWS S3 bucket for Drone N' Go image storage.

---

## Step 1 — Create an AWS Account

If you don't already have one, go to [aws.amazon.com](https://aws.amazon.com) and create an account.

---

## Step 2 — Create an S3 Bucket

1. Go to the [S3 Console](https://s3.console.aws.amazon.com/s3)
2. Click **Create bucket**
3. Set the **Bucket name** — e.g. `droneandgo-images`
4. Select your **AWS Region** — e.g. `us-east-1`
5. Under **Block Public Access settings**, **uncheck** "Block all public access" (drone images need to be publicly viewable)
6. Confirm the warning checkbox
7. Leave all other settings as default
8. Click **Create bucket**

---

## Step 3 — Add a Bucket Policy for Public Read

1. Open your new bucket → **Permissions** tab → **Bucket policy**
2. Paste the following, replacing `YOUR-BUCKET-NAME`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PublicReadGetObject",
      "Effect": "Allow",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::YOUR-BUCKET-NAME/*"
    }
  ]
}
```

3. Click **Save changes**

---

## Step 4 — Create an IAM User

1. Go to [IAM Console](https://console.aws.amazon.com/iam) → **Users** → **Create user**
2. Username: `droneandgo-api`
3. Select **Attach policies directly**
4. Search for and attach `AmazonS3FullAccess` (or create a scoped policy — see below)
5. Click **Create user**

### Optional: Scoped IAM Policy (Recommended for Production)

Instead of `AmazonS3FullAccess`, create a custom policy with only what the API needs:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::YOUR-BUCKET-NAME/*"
    }
  ]
}
```

---

## Step 5 — Generate Access Keys

1. Click your new IAM user → **Security credentials** tab
2. Under **Access keys**, click **Create access key**
3. Choose **Application running outside AWS**
4. Click **Create access key**
5. **Copy both keys now** — the secret is only shown once

---

## Step 6 — Add Keys to .env

```env
AWS_ACCESS_KEY_ID="AKIA..."
AWS_SECRET_ACCESS_KEY="abc123..."
AWS_REGION="us-east-1"
AWS_S3_BUCKET="droneandgo-images"
```

---

## Step 7 — Verify

Start the API and upload a test image via:

```
POST /api/bookings/{booking_id}/images/pre-rental
```

You should see a URL like:
```
https://droneandgo-images.s3.us-east-1.amazonaws.com/drone-images/pre-rental/<booking_id>/<uuid>.jpg
```

Paste that URL into a browser — if the image loads, you're done.
