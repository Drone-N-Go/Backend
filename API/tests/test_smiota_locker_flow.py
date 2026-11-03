"""End-to-end Smiota locker flow against a real Postgres database (added 2026-11-02).

Covers two production bugs:
  - A returned drone never came back into the catalog: pickup and return both
    unlinked the drone from its locker unit, and the return deposit was
    ignored because it matched the old booking.
  - Stale Smiota object IDs: every booking of a drone inherited the same
    objectId, so once two bookings shared it the event lookup raised
    MultipleResultsFound (a 500) or matched an old, finished booking.

These tests need a migrated database. Set TEST_DATABASE_URL to a throwaway
Postgres database (`alembic upgrade head` against it first); they are
skipped otherwise. Every test truncates the tables it uses.
"""

import os
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest import IsolatedAsyncioTestCase

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.models.booking import Booking
from app.models.drone import Drone
from app.models.locker_location import LockerLocation
from app.models.locker_unit import LockerUnit
from app.models.smiota_event import SmiotaEvent
from app.models.user import User
from app.schemas.booking import BookingCreateRequest
from app.schemas.webhook import SmiotaWebhookRequest
from app.services import booking_service, drone_service, webhook_service

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")


def _async_url(url: str) -> str:
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)


@unittest.skipUnless(TEST_DATABASE_URL, "TEST_DATABASE_URL not set; skipping real-database locker flow tests")
class SmiotaLockerFlowTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine(_async_url(TEST_DATABASE_URL))
        self.Session = sessionmaker(bind=self.engine, class_=AsyncSession, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.execute(text(
                "TRUNCATE smiota_events, damage_reports, bookings, locker_units, "
                "drones, locker_locations, users RESTART IDENTITY CASCADE"
            ))

    async def asyncTearDown(self):
        await self.engine.dispose()

    # ------------------------------------------------------------------ #
    # Helpers: each step runs in its own committed session, like a request.
    # ------------------------------------------------------------------ #

    async def step(self, fn):
        async with self.Session() as session:
            result = await fn(session)
            await session.commit()
            return result

    async def make_user(self, email: str) -> User:
        async def _do(db):
            user = User(email=email, password_hash="x", first_name="Test", last_name="Renter")
            db.add(user)
            await db.flush()
            return user
        return await self.step(_do)

    async def make_locker_with_drone(self, locker_name: str, serial: str, unit_number: str = "1"):
        """A location with one cabinet that an admin has linked a drone to
        (what intake does: unit.current_drone_id + unit.status occupied)."""
        async def _do(db):
            location = LockerLocation(
                campus_name=f"Campus {serial}", address="1 Test Way", latitude=29.4, longitude=-98.5
            )
            db.add(location)
            await db.flush()
            drone = Drone(
                model_name="Mavic 4 Pro",
                serial_number=serial,
                hourly_rate=Decimal("1.46"),
                daily_rate=Decimal("35.00"),
                status="available",
                assigned_locker_location_id=location.id,
            )
            db.add(drone)
            await db.flush()
            unit = LockerUnit(
                location_id=location.id,
                unit_number=unit_number,
                smiota_locker_name=locker_name,
                current_drone_id=drone.id,
                status="occupied",
            )
            db.add(unit)
            await db.flush()
            return location.id, drone.id, unit.id
        return await self.step(_do)

    async def webhook(self, notification_type: str, object_id: str, locker_name: str | None, passcode: str | None = None):
        body = SmiotaWebhookRequest(
            notification_type=notification_type,
            objectId=object_id,
            lockerName=locker_name,
            passcode=passcode,
            courierCode="COUR-1",
        )
        return await self.step(lambda db: webhook_service.process_smiota_webhook(body, db))

    async def book(self, user: User, drone_id: str, location_id: str) -> Booking:
        body = BookingCreateRequest(
            drone_id=drone_id,
            location_id=location_id,
            pickup_time=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            rental_duration=1,
            rental_type="daily",
        )
        return await self.step(lambda db: booking_service.create_booking(body, user, db))

    async def set_status(self, booking_id: str, status: str):
        async def _do(db):
            booking = await db.get(Booking, booking_id)
            booking.status = status
        await self.step(_do)

    async def return_drone(self, user: User, booking_id: str):
        """Walk a picked-up booking to the end of the return flow. The
        evidence-upload steps are covered elsewhere; this jumps the status
        straight to return_video_complete, the state complete_return needs."""
        await self.set_status(booking_id, "return_video_complete")
        await self.step(lambda db: booking_service.complete_return(booking_id, None, user, db))

    async def get(self, model, pk):
        async with self.Session() as db:
            return await db.get(model, pk)

    async def available_drone_ids(self) -> set[str]:
        async with self.Session() as db:
            listing = await drone_service.list_drones(db, status_filter="available")
            return {item.id for item in listing.items}

    async def rent_and_return(self, user, drone_id, location_id, locker_name, return_passcode):
        """One complete real-world rental: book, pickup, return deposit, complete."""
        booking = await self.book(user, drone_id, location_id)
        await self.set_status(booking.id, "locker_opened")
        await self.webhook("PackagePickedUp", "Mavic Pro", locker_name)
        await self.set_status(booking.id, "return_locker_opened")
        await self.webhook("PackageDeposited", "Mavic Pro", locker_name, passcode=return_passcode)
        await self.return_drone(user, booking.id)
        return booking

    # ------------------------------------------------------------------ #
    # Item 6: returned drones come back into the catalog
    # ------------------------------------------------------------------ #

    async def test_returned_drone_is_listed_again_with_the_return_passcode(self):
        location_id, drone_id, unit_id = await self.make_locker_with_drone("Locker 1", "SN-1")
        renter = await self.make_user("renter1@example.com")
        next_renter = await self.make_user("renter2@example.com")

        # Staff stock the locker; the drone is offered for rental.
        await self.webhook("PackageDeposited", "Mavic Pro", "Locker 1", passcode="111111")
        self.assertIn(drone_id, await self.available_drone_ids())

        booking = await self.book(renter, drone_id, location_id)
        self.assertEqual(booking.status, "ready_for_pickup")
        self.assertEqual(booking.smiota_passcode, "111111")

        # Pickup: the drone leaves the cabinet but stays linked to it.
        await self.set_status(booking.id, "locker_opened")
        await self.webhook("PackagePickedUp", "Mavic Pro", "Locker 1")
        unit = await self.get(LockerUnit, unit_id)
        self.assertEqual(unit.current_drone_id, drone_id)
        self.assertIsNone(unit.current_passcode)
        self.assertNotIn(drone_id, await self.available_drone_ids())

        # Return deposit arrives mid-return: passcode stored, drone not yet bookable.
        await self.set_status(booking.id, "return_locker_opened")
        await self.webhook("PackageDeposited", "Mavic Pro", "Locker 1", passcode="222222")
        unit = await self.get(LockerUnit, unit_id)
        self.assertEqual(unit.current_passcode, "222222")
        self.assertEqual((await self.get(Drone, drone_id)).status, "rented")
        self.assertNotIn(drone_id, await self.available_drone_ids())

        # Renter finishes the return: drone is back in the catalog, same cabinet.
        await self.return_drone(renter, booking.id)
        unit = await self.get(LockerUnit, unit_id)
        self.assertEqual(unit.current_drone_id, drone_id)
        self.assertEqual((await self.get(Drone, drone_id)).status, "available")
        self.assertIn(drone_id, await self.available_drone_ids())

        # The next renter gets the code from the return deposit, not the old one.
        second = await self.book(next_renter, drone_id, location_id)
        self.assertEqual(second.status, "ready_for_pickup")
        self.assertEqual(second.smiota_passcode, "222222")

    async def test_return_completed_before_the_deposit_event_still_relists(self):
        location_id, drone_id, unit_id = await self.make_locker_with_drone("Locker 1", "SN-1")
        renter = await self.make_user("renter1@example.com")

        await self.webhook("PackageDeposited", "Mavic Pro", "Locker 1", passcode="111111")
        booking = await self.book(renter, drone_id, location_id)
        await self.set_status(booking.id, "locker_opened")
        await self.webhook("PackagePickedUp", "Mavic Pro", "Locker 1")

        # The app finishes the return before Smiota's deposit webhook lands.
        await self.return_drone(renter, booking.id)
        self.assertEqual((await self.get(LockerUnit, unit_id)).current_drone_id, drone_id)

        await self.webhook("PackageDeposited", "Mavic Pro", "Locker 1", passcode="333333")
        unit = await self.get(LockerUnit, unit_id)
        self.assertEqual(unit.current_passcode, "333333")
        self.assertIn(drone_id, await self.available_drone_ids())

    async def test_booking_made_before_the_return_deposit_gets_its_passcode_when_it_lands(self):
        location_id, drone_id, unit_id = await self.make_locker_with_drone("Locker 1", "SN-1")
        renter = await self.make_user("renter1@example.com")
        next_renter = await self.make_user("renter2@example.com")

        await self.webhook("PackageDeposited", "Mavic Pro", "Locker 1", passcode="111111")
        booking = await self.book(renter, drone_id, location_id)
        await self.set_status(booking.id, "locker_opened")
        await self.webhook("PackagePickedUp", "Mavic Pro", "Locker 1")
        await self.return_drone(renter, booking.id)

        # Booked in the gap between the app's return and Smiota's deposit event:
        # no passcode yet, so it waits in `reserved`.
        second = await self.book(next_renter, drone_id, location_id)
        self.assertEqual(second.status, "reserved")

        await self.webhook("PackageDeposited", "Mavic Pro", "Locker 1", passcode="444444")
        second = await self.get(Booking, second.id)
        self.assertEqual(second.status, "ready_for_pickup")
        self.assertEqual(second.smiota_passcode, "444444")

    async def test_damaged_return_stays_linked_but_is_not_listed(self):
        location_id, drone_id, unit_id = await self.make_locker_with_drone("Locker 1", "SN-1")
        renter = await self.make_user("renter1@example.com")

        await self.webhook("PackageDeposited", "Mavic Pro", "Locker 1", passcode="111111")
        booking = await self.book(renter, drone_id, location_id)
        await self.set_status(booking.id, "locker_opened")
        await self.webhook("PackagePickedUp", "Mavic Pro", "Locker 1")
        await self.set_status(booking.id, "return_locker_opened")
        await self.webhook("PackageDeposited", "Mavic Pro", "Locker 1", passcode="222222")

        async def mark_damaged(db):
            drone = await db.get(Drone, drone_id)
            drone.status = "damaged"
        await self.step(mark_damaged)
        await self.webhook("PackageDeposited", "Mavic Pro", "Locker 1", passcode="222223")

        self.assertEqual((await self.get(LockerUnit, unit_id)).current_drone_id, drone_id)
        self.assertEqual((await self.get(Drone, drone_id)).status, "damaged")
        self.assertNotIn(drone_id, await self.available_drone_ids())

    # ------------------------------------------------------------------ #
    # Item 7: stale Smiota object IDs
    # ------------------------------------------------------------------ #

    async def test_repeat_rentals_sharing_an_object_id_keep_processing(self):
        location_id, drone_id, unit_id = await self.make_locker_with_drone("Locker 1", "SN-1")
        await self.webhook("PackageDeposited", "Mavic Pro", "Locker 1", passcode="111111")

        # Three back-to-back rentals; Smiota labels every deposit "Mavic Pro".
        renters = [await self.make_user(f"r{i}@example.com") for i in range(3)]
        for i, renter in enumerate(renters):
            await self.rent_and_return(renter, drone_id, location_id, "Locker 1", f"55555{i}")

        # Every event was processed; none failed or blew up with a 500.
        async with self.Session() as db:
            statuses = (await db.execute(select(SmiotaEvent.processing_status))).scalars().all()
        self.assertTrue(statuses)
        self.assertNotIn("failed", statuses)
        self.assertIn(drone_id, await self.available_drone_ids())

        # A fourth rental still works and picks up the latest code.
        fourth = await self.book(await self.make_user("r4@example.com"), drone_id, location_id)
        self.assertEqual(fourth.smiota_passcode, "555552")

    async def test_pickup_event_never_touches_a_finished_booking(self):
        location_id, drone_id, unit_id = await self.make_locker_with_drone("Locker 1", "SN-1")
        await self.webhook("PackageDeposited", "Mavic Pro", "Locker 1", passcode="111111")
        old = await self.rent_and_return(await self.make_user("old@example.com"), drone_id, location_id, "Locker 1", "222222")

        current = await self.book(await self.make_user("new@example.com"), drone_id, location_id)
        await self.set_status(current.id, "locker_opened")
        response = await self.webhook("PackagePickedUp", "Mavic Pro", "Locker 1")

        self.assertEqual(response.booking_id, current.id)
        self.assertEqual((await self.get(Booking, old.id)).status, "returned")

    async def test_same_object_id_in_two_lockers_resolves_by_locker(self):
        loc_a, drone_a, unit_a = await self.make_locker_with_drone("Locker A", "SN-A")
        loc_b, drone_b, unit_b = await self.make_locker_with_drone("Locker B", "SN-B")
        await self.webhook("PackageDeposited", "Mavic Pro", "Locker A", passcode="100001")
        await self.webhook("PackageDeposited", "Mavic Pro", "Locker B", passcode="200002")

        booking_a = await self.book(await self.make_user("a@example.com"), drone_a, loc_a)
        booking_b = await self.book(await self.make_user("b@example.com"), drone_b, loc_b)
        self.assertEqual(booking_a.smiota_passcode, "100001")
        self.assertEqual(booking_b.smiota_passcode, "200002")

        response = await self.webhook("PackagePickedUp", "Mavic Pro", "Locker B")
        self.assertEqual(response.booking_id, booking_b.id)
        self.assertIsNone((await self.get(LockerUnit, unit_b)).current_passcode)
        self.assertEqual((await self.get(LockerUnit, unit_a)).current_passcode, "100001")

    async def test_pickup_clears_the_deposit_ids_held_on_the_cabinet(self):
        location_id, drone_id, unit_id = await self.make_locker_with_drone("Locker 1", "SN-1")
        await self.webhook("PackageDeposited", "Mavic Pro", "Locker 1", passcode="111111")
        booking = await self.book(await self.make_user("r@example.com"), drone_id, location_id)
        await self.set_status(booking.id, "locker_opened")
        await self.webhook("PackagePickedUp", "Mavic Pro", "Locker 1")

        metadata = (await self.get(LockerUnit, unit_id)).smiota_metadata or {}
        self.assertNotIn("pending_deposit_object_id", metadata)
        self.assertNotIn("pending_deposit_courier_code", metadata)

    async def test_cancelled_booking_leaves_the_deposit_for_the_next_renter(self):
        location_id, drone_id, unit_id = await self.make_locker_with_drone("Locker 1", "SN-1")
        await self.webhook("PackageDeposited", "Mavic Pro", "Locker 1", passcode="111111")
        first_user = await self.make_user("r1@example.com")
        first = await self.book(first_user, drone_id, location_id)
        await self.step(lambda db: booking_service.cancel_booking(first.id, first_user, db))

        second = await self.book(await self.make_user("r2@example.com"), drone_id, location_id)
        self.assertEqual(second.status, "ready_for_pickup")
        self.assertEqual(second.smiota_passcode, "111111")

        await self.set_status(second.id, "locker_opened")
        response = await self.webhook("PackagePickedUp", "Mavic Pro", "Locker 1")
        self.assertEqual(response.booking_id, second.id)

    async def test_deposit_without_locker_name_falls_back_to_the_active_booking(self):
        location_id, drone_id, unit_id = await self.make_locker_with_drone("Locker 1", "SN-1")
        await self.webhook("PackageDeposited", "Mavic Pro", "Locker 1", passcode="111111")
        old = await self.rent_and_return(await self.make_user("old@example.com"), drone_id, location_id, "Locker 1", "222222")
        current = await self.book(await self.make_user("new@example.com"), drone_id, location_id)
        await self.set_status(current.id, "locker_opened")

        # No lockerName: matched by objectId, but only among active bookings.
        response = await self.webhook("PackagePickedUp", "Mavic Pro", None)
        self.assertEqual(response.booking_id, current.id)
        self.assertEqual((await self.get(Booking, old.id)).status, "returned")


if __name__ == "__main__":
    unittest.main()
