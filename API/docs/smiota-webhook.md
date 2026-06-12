# Smiota Webhook Integration

This document describes how Drone N' Go integrates with Smiota smart lockers.

---

## Overview

When a drone is placed in or picked up from a Smiota locker, Smiota sends a `POST` request to our webhook endpoint. The API uses this to:

1. Store the locker passcode on the booking (`PackageDeposited`)
2. Audit locker pickup events without skipping the app-driven verification flow (`PackagePickedUp`)
3. Feed the Admin locker dashboard through explicit Smiota-to-locker-unit mapping

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
  "courierCode": "COUR-XYZ",
  "trackingID": "TRK-9876543210"
}
```

| Field | Type | Description |
|---|---|---|
| `notification_type` | string | `PackageDeposited` or `PackagePickedUp` |
| `objectId` | string | Smiota object ID — must match `smiota_object_id` on a booking |
| `lockerName` | string | Human-readable locker name |
| `passcode` | string | Numeric passcode for locker access |
| `courierCode` | string | Optional courier/delivery code |
| `trackingID` | string | Optional Smiota tracking ID |

---

## Event Handling

### `PackageDeposited`
Triggered when staff deposits a drone into the locker.

- Stores `passcode`, `lockerName`, and `courierCode` on the booking
- Stores `trackingID` in the Smiota event audit log
- Moves booking `reserved` → `ready_for_pickup`
- User can now call `GET /api/bookings/{id}/passcode` to retrieve their code

---

### `PackagePickedUp`
Triggered when the user opens the locker and picks up the drone.

- Records the raw Smiota event
- Keeps the drone status → `rented`
- Does not advance the booking past `ready_for_pickup`; the iOS flow must still confirm locker opened, QR verification, before photos, and start-use

---

## Matching a Booking to a Smiota Object

Before Smiota events can be matched to a booking, the booking must already have a `smiota_object_id` value from the internal locker provisioning flow. The public API no longer exposes a manual link endpoint.

---

## Mapping Smiota to Locker Units

Admin locker state uses explicit mapping fields on `locker_units`:

- `smiota_locker_name`
- `smiota_unit_identifier`
- `smiota_metadata`

The Admin API uses these fields to connect raw Smiota events to internal locker units. Passcodes are masked in `GET /api/admin/lockers/current-state` and only returned by `POST /api/admin/lockers/{locker_unit_id}/reveal-passcode`, which writes a `locker_access_events` audit record.

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
  -u "YOUR_SMIOTA_API_KEY_HERE:" \
  -H "Content-Type: application/json" \
  -d '{
    "notification_type": "PackageDeposited",
    "objectId": "smiota-obj-abc123",
    "lockerName": "Locker-A3",
    "passcode": "849201",
    "courierCode": "COUR-XYZ",
    "trackingID": "TRK-9876543210"
  }'
```

Note the trailing colon after the API key — that's the empty password in Basic Auth format.
