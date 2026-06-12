# Endpoint Reference

Full reference for all Drone N' Go API endpoints.

---

## Authentication

### `POST /api/auth/register`
Register a new user account. Returns JWT tokens.

**Request body:**
```json
{
  "email": "user@example.com",
  "password": "secret123",
  "first_name": "Jane",
  "last_name": "Doe",
  "address": "123 Main St",
  "school": "University of Missouri"
}
```

---

### `POST /api/auth/login`
Authenticate and receive JWT tokens.

**Request body:**
```json
{ "email": "user@example.com", "password": "secret123" }
```

---

### `POST /api/auth/logout`
Clears `access_token` and `refresh_token` cookies.

---

### `GET /api/auth/me`
Returns the authenticated user's profile. Requires: `User`.

---

### `POST /api/auth/refresh`
Exchange a refresh token (from cookie) for a new access token.

---

## Users

### `GET /api/users/me/profile`
Get the authenticated user's profile. Requires: `User`.

---

### `PUT /api/users/me/profile`
Update the authenticated user's profile. Requires: `User`.

```json
{ "first_name": "Jane", "last_name": "Smith", "school": "Mizzou" }
```

---

## Drones

### `GET /api/drones`
List all drones. Public.

Query params: `status` (`available`|`rented`|`damaged`|`maintenance`), `location_id`, `skip`, `limit`

---

### `GET /api/drones/{drone_id}`
Get a single drone by ID. Public.

---

## Locations & Lockers

### `GET /api/locations`
List all locker locations. Public.

---

### `GET /api/locations/{location_id}`
Get a location with all its locker units. Public.

---

### `GET /api/locations/{location_id}/units`
List locker units at a location. Public.

---

## Bookings

### `POST /api/bookings`
Create a booking. Requires: `User`. Marks drone as `rented`.

```json
{
  "drone_id": "<uuid>",
  "location_id": "<uuid>",
  "pickup_time": "2025-06-01T10:00:00Z",
  "rental_duration": 4,
  "rental_type": "hourly"
}
```

---

### `GET /api/bookings`
List the authenticated user's bookings.

Query params: `status`, `skip`, `limit`

---

### `GET /api/bookings/{booking_id}`
Get a single booking owned by the authenticated user.

---

### `GET /api/bookings/{booking_id}/passcode`
Get the Smiota locker passcode. Available after `PackageDeposited` webhook.

---

### `PATCH /api/bookings/{booking_id}/cancel`
Cancel a booking. Frees the drone back to `available`.

---

### `POST /api/bookings/{booking_id}/images/pre-rental`
Upload pre-rental drone condition images. `multipart/form-data`, field: `files`.

---

### `POST /api/bookings/{booking_id}/images/post-rental`
Upload post-rental drone condition images. `multipart/form-data`, field: `files`.

---

### `POST /api/bookings/{booking_id}/return-video`
Upload the required return video. `multipart/form-data`, field: `file`.

---

### `GET /api/bookings/{booking_id}/images`
Get all condition images for a booking.

---

### Lifecycle transition endpoints
Each endpoint returns the updated booking. Skipped or backwards transitions return `409 Conflict`; retrying the current transition is idempotent.

```text
POST /api/bookings/{booking_id}/locker-opened
POST /api/bookings/{booking_id}/case-verified
POST /api/bookings/{booking_id}/before-photos/complete
POST /api/bookings/{booking_id}/start-use
POST /api/bookings/{booking_id}/return/start
POST /api/bookings/{booking_id}/after-photos/complete
POST /api/bookings/{booking_id}/return-locker-opened
POST /api/bookings/{booking_id}/return-video/complete
POST /api/bookings/{booking_id}/complete-return
```

Evidence completion endpoints accept a development/demo override:

```json
{ "skip_evidence_check": true }
```

Complete return accepts optional notes:

```json
{ "notes": "Minor scuff on left arm noticed." }
```

---

## Webhooks

### `POST /api/webhooks/smiota`
Smiota locker event receiver. Auth: HTTP Basic (`SMIOTA_API_KEY` as username).

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

Supported `notification_type` values: `PackageDeposited`, `PackagePickedUp`

---

## Admin

Admin endpoints use the normal JWT bearer token, then require an active `admin_profiles` row linked to that user.

Roles:

- `owner` — full access.
- `master_developer` — full access.
- `manager` — full access except Owner/Master Developer account management.
- `developer` — platform and operations access, excluding money and Owner/Master Developer account management.
- `admin` — assigned-location operations, maintenance, support, locker state, and audited passcode reveal.

### `POST /api/admin/setup/owner`
Create the first Owner account and admin profile. This endpoint only works while there are zero active admin profiles; future calls return `409`.

```json
{
  "email": "owner@droneandgo.io",
  "password": "secret123",
  "first_name": "James",
  "last_name": "McDougall",
  "title": "Owner"
}
```

---

### `GET /api/admin/me`
Return the current admin profile, capabilities, and assigned location IDs.

---

### `GET /api/admin/staff`
List admin staff profiles. Requires staff-management capability.

---

### `POST /api/admin/staff`
Create staff and assign optional locations. Managers and Developers cannot manage Owner or Master Developer accounts.

```json
{
  "email": "tech@example.com",
  "password": "secret123",
  "first_name": "Campus",
  "last_name": "Tech",
  "role": "admin",
  "assigned_location_ids": ["<location-id>"]
}
```

---

### `PATCH /api/admin/staff/{profile_id}/status`
Suspend or reactivate a staff profile.

```json
{ "status": "suspended" }
```

---

### `GET /api/admin/lockers/current-state`
List locker units in the admin's scope. Passcodes are masked and only exposed through audited reveal.

Query params: `location_id`, `skip`, `limit`

---

### `POST /api/admin/lockers/{locker_unit_id}/reveal-passcode`
Reveal the current Smiota passcode for a mapped locker and write a `locker_access_events` audit record.

```json
{
  "reason": "Opening locker for drone maintenance",
  "app_context": { "platform": "ios" }
}
```

---

### `PATCH /api/admin/lockers/{locker_unit_id}/mapping`
Attach explicit Smiota identifiers to a locker unit.

```json
{
  "smiota_locker_name": "Locker-A3",
  "smiota_unit_identifier": "smiota-unit-a3",
  "smiota_metadata": {}
}
```

---

### `PATCH /api/admin/lockers/{locker_unit_id}/maintenance`
Update locker status with a reason.

```json
{ "status": "maintenance", "reason": "Keypad unresponsive" }
```

---

### `PATCH /api/admin/lockers/{locker_unit_id}/drone`
Assign or unassign the current drone in a locker.

```json
{ "drone_id": "<drone-id>" }
```

Use `{"drone_id": null}` to unassign.

---

### `GET /api/admin/maintenance/tasks`
List maintenance tasks in scope.

---

### `POST /api/admin/maintenance/tasks`
Create a maintenance task.

```json
{
  "title": "Inspect locker A3",
  "location_id": "<location-id>",
  "locker_unit_id": "<locker-unit-id>",
  "priority": "normal"
}
```

---

### `PATCH /api/admin/maintenance/tasks/{task_id}`
Update task status, assignment, or resolution notes.

---

### `GET /api/admin/stats`
Return role-aware stats. Money totals are omitted for Developer and Admin roles.

---

### `GET /api/admin/smiota/unmapped-events`
Return recent Smiota events that do not map to a locker unit. Requires global admin scope.
