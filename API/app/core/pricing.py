"""Standard rental pricing for every drone.

$35 per day. The hourly rate is the daily rate divided by 24 (~$1.4583/hr).
These apply to every drone regardless of the hourly_rate / daily_rate stored
on the drone row — those columns are kept (the admin create-drone flow still
requires them) but are no longer used for display or for charging.

RENTAL_PRICE_OVERRIDE (env var), when set, still replaces this with one flat
price per rental — see booking_service._calculate_cost.
"""

from decimal import ROUND_HALF_UP, Decimal

DAILY_RATE = Decimal("35.00")
HOURLY_RATE = DAILY_RATE / Decimal(24)

# Sent to the apps/website. Four decimal places so a client multiplying
# hours x rate lands on the same cent the server charges.
HOURLY_RATE_DISPLAY = HOURLY_RATE.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

_CENT = Decimal("0.01")


def rental_cost(rental_type: str, duration: int) -> Decimal:
    """Total for `duration` hours (hourly) or days (daily), rounded to the cent."""
    rate = HOURLY_RATE if rental_type == "hourly" else DAILY_RATE
    return (rate * Decimal(duration)).quantize(_CENT, rounding=ROUND_HALF_UP)
