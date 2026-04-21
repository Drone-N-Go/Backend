"""
app/db/base.py
--------------
Declarative base that all SQLAlchemy ORM models inherit from.
Import all models here so Alembic's autogenerate can discover them.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Import all models so that Alembic sees them during autogenerate.
# Keep this list up to date whenever you add a new model.
# ---------------------------------------------------------------------------
from app.models.user import User                        # noqa: F401, E402
from app.models.drone import Drone                      # noqa: F401, E402
from app.models.locker_location import LockerLocation   # noqa: F401, E402
from app.models.locker_unit import LockerUnit           # noqa: F401, E402
from app.models.booking import Booking                  # noqa: F401, E402
from app.models.damage_report import DamageReport       # noqa: F401, E402
from app.models.smiota_event import SmiotaEvent         # noqa: F401, E402
from app.models.login_attempt import LoginAttempt       # noqa: F401, E402
