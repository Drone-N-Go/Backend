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

### `POST /api/auth/create-admin`
Create a new admin account. Requires: `Admin`.

```json
{ "email": "newadmin@droneandgo.io", "password": "secure", "first_name": "Bob", "last_name": "Smith" }
```

---

## Users

### `GET /api/users`
List all users with pagination. Requires: `Admin`.

Query params: `skip`, `limit`, `role` (`user` | `admin`)

---

### `GET /api/users/me/profile`
Get the authenticated user's profile. Requires: `User`.

---

### `PUT /api/users/me/profile`
Update the authenticated user's profile. Requires: `User`.

```json
{ "first_name": "Jane", "last_name": "Smith", "school": "Mizzou" }
```

---

### `GET /api/users/{user_id}`
Get a specific user by ID. Requires: `Admin`.

---

### `GET /api/users/{user_id}/rentals`
Get rental history for a specific user. Requires: `Admin`.

---

## Drones

### `GET /api/drones`
List all drones. Public.

Query params: `status` (`available`|`rented`|`damaged`|`maintenance`), `location_id`, `skip`, `limit`

---

### `GET /api/drones/{drone_id}`
Get a single drone by ID. Public.

---

### `POST /api/drones`
Create a drone. Requires: `Admin`.

```json
{
  "model_name": "DJI Mini 4 Pro",
  "serial_number": "SN-001-2024",
  "assigned_locker_location_id": "<uuid>",
  "hourly_rate": 15.00,
  "daily_rate": 75.00
}
```

---

### `PUT /api/drones/{drone_id}`
Update drone details. Requires: `Admin`.

---

### `DELETE /api/drones/{drone_id}`
Delete a drone. Requires: `Admin`.

---

### `PATCH /api/drones/{drone_id}/status`
Override drone status. Requires: `Admin`.

```json
{ "status": "maintenance" }
```

---

## Locations & Lockers

### `GET /api/locations`
List all locker locations. Public.

---

### `GET /api/locations/{location_id}`
Get a location with all its locker units. Public.

---

### `POST /api/locations`
Create a locker location. Requires: `Admin`.

```json
{
  "campus_name": "University of Missouri",
  "address": "Columbia, MO 65201",
  "latitude": 38.9404,
  "longitude": -92.3277,
  "building_name": "Lafferre Hall",
  "landmarks": "Near the engineering fountain",
  "directions": "Enter through the north entrance, lockers are on the right."
}
```

---

### `PUT /api/locations/{location_id}` — Update. Requires: `Admin`.
### `DELETE /api/locations/{location_id}` — Delete. Requires: `Admin`.

---

### `GET /api/locations/{location_id}/units`
List locker units at a location. Public.

---

### `POST /api/locations/{location_id}/units`
Add a locker unit. Requires: `Admin`.

```json
{ "unit_number": "A3", "status": "available" }
```

---

### `PUT /api/locations/{location_id}/units/{unit_id}` — Update unit. Requires: `Admin`.
### `DELETE /api/locations/{location_id}/units/{unit_id}` — Delete unit. Requires: `Admin`.

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
List bookings. Users see only their own. Admins see all.

Query params: `status`, `skip`, `limit`

---

### `GET /api/bookings/{booking_id}`
Get a single booking. Owner or admin only.

---

### `GET /api/bookings/{booking_id}/passcode`
Get the Smiota locker passcode. Available after `PackageDeposited` webhook.

---

### `PATCH /api/bookings/{booking_id}/cancel`
Cancel a booking. Frees the drone back to `available`.

---

### `PATCH /api/bookings/{booking_id}/status`
Manually update booking status. Requires: `Admin`.

```json
{ "status": "active" }
```

---

### `PATCH /api/bookings/{booking_id}/smiota-link`
Link a Smiota `objectId` to a booking. Requires: `Admin`.

```json
{ "smiota_object_id": "smiota-obj-abc123" }
```

---

### `POST /api/bookings/{booking_id}/images/pre-rental`
Upload pre-rental drone condition images. `multipart/form-data`, field: `files`.

---

### `POST /api/bookings/{booking_id}/images/post-rental`
Upload post-rental drone condition images. `multipart/form-data`, field: `files`.

---

### `GET /api/bookings/{booking_id}/images`
Get all condition images for a booking.

---

### `POST /api/bookings/{booking_id}/return`
Return a drone. Sets booking to `completed`. Creates a damage report if none exists.

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
  "courierCode": "COUR-XYZ"
}
```

Supported `notification_type` values: `PackageDeposited`, `PackagePickedUp`

---

## Admin

### `GET /api/admin/analytics`
Full business analytics dashboard. Requires: `Admin`.

Query params: `days` (default `30`, max `365`)

---

### `PATCH /api/admin/drones/{drone_id}/condition`
Review drone condition after return. Requires: `Admin`.

```json
{
  "condition_status": "undamaged",
  "admin_notes": "Inspected, all good."
}
```

`condition_status` values: `undamaged` | `damaged` | `needs_review`
