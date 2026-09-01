"""Backfill locker_units.smiota_locker_name to match unit_number.

Root cause: locker_units.smiota_locker_name was populated with the shared
physical-tower serial (e.g. "D&GL-0001") duplicated across every cabinet
row, instead of the per-cabinet identifier Smiota's webhook actually sends
in `lockerName`. Smiota's hardware/dashboard is currently locked to sending
bare cabinet numbers ("1"-"5") with no way to reconfigure it and no
location/site field in the payload at all, so with a single physical
location the safe, correct match value for each cabinet is simply its own
unit_number.

This is a one-time backfill scoped to the current single-location setup.
If/when a second physical location is added, this unconditional
"smiota_locker_name = unit_number" mapping will collide across locations
(cabinet "1" would exist at both sites with nothing in the Smiota payload
to disambiguate them) and will need to be revisited then.

Revision ID: 20260901_0011
Revises: 20260901_0010
Create Date: 2026-09-01
"""

from alembic import op


revision = "20260901_0011"
down_revision = "20260901_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE locker_units SET smiota_locker_name = unit_number;")


def downgrade() -> None:
    # The prior values were not meaningfully distinct (all shared one
    # placeholder like "D&GL-0001"), so there is nothing correct to restore.
    # Leaving smiota_locker_name set to unit_number on downgrade is the safer
    # no-op; if you truly need the old placeholder back, set it manually.
    pass
