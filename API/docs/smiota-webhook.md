# Smiota Webhook Integration

This document describes how Drone N' Go integrates with Smiota smart lockers.

---

## Overview

When a drone is placed in or picked up from a Smiota locker, Smiota sends a `POST` request to our webhook endpoint. The API uses this to:

1. Store the locker passcode on the booking (`PackageDeposited`)
2. Activate the booking when the user picks up the drone (`PackagePickedUp`)

---

## Webhook Endpoint

```
POST /api/webhooks/smiota
```

### Authentication

HTTP Basic Auth — Smiota sends the API key as the **username**, with an **empty password**.

Configure your `SMIOTA_API_KEY` in `.env`. Provide this key to Smiota when setting up the webhook in their dashboard.

---

## Payload Format

```json
{
  "notification_type": "PackageDeposited",
  "objectId": "smiota-obj-abc123",
  "lockerName": "Locker-A3",
  "passcode": "849201",
  "courierCode": "COUR-XYZ"
}
```

| Field | Type | Description |
|---|---|---|
| `notification_type` | string | `PackageDeposited` or `PackagePickedUp` |
| `objectId` | string | Smiota object ID — must match `smiota_object_id` on a booking |
| `lockerName` | string | Human-readable locker name |
| `passcode` | string | Numeric passcode for locker access |
| `courierCode` | string | Optional courier/delivery code |

---

## Event Handling

### `PackageDeposited`
Triggered when staff deposits a drone into the locker.

- Stores `passcode`, `lockerName`, and `courierCode` on the booking
- Moves booking `reserved` → `ready_for_pickup`
- User can now call `GET /api/bookings/{id}/passcode` to retrieve their code

---

### `PackagePickedUp`
Triggered when the user opens the locker and picks up the drone.

- Records the raw Smiota event
- Keeps the drone status → `rented`
- Does not advance the booking past `ready_for_pickup`; the iOS flow must still confirm locker opened, QR verification, before photos, and start-use

---

## Linking a Booking to a Smiota Object

Before Smiota events can be matched to a booking, an admin must link the `smiota_object_id`:

```
PATCH /api/bookings/{booking_id}/smiota-link
```

```json
{ "smiota_object_id": "smiota-obj-abc123" }
```

This is the bridge between your booking system and Smiota's object ID.

---

## Event Log

All raw webhook payloads are stored in the `smiota_events` table for debugging and auditing. Each event has a `processed` boolean flag.

---

## Testing the Webhook Locally

Use a tool like [ngrok](https://ngrok.com) to expose your local server:

```bash
ngrok http 8000
```

Then configure Smiota's webhook URL to:
```
https://<your-ngrok-subdomain>.ngrok.io/api/webhooks/smiota
```

You can also test manually with curl:

```bash
curl -X POST http://localhost:8000/api/webhooks/smiota \
  -u "sk_smiota_dronengo_x9k2m4p7q1w3e5r8t0y6:" \
  -H "Content-Type: application/json" \
  -d '{
    "notification_type": "PackageDeposited",
    "objectId": "smiota-obj-abc123",
    "lockerName": "Locker-A3",
    "passcode": "849201",
    "courierCode": "COUR-XYZ"
  }'
```

Note the trailing colon after the API key — that's the empty password in Basic Auth format.
