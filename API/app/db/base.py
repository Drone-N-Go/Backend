"""
app/db/base.py
--------------
Declarative base that all SQLAlchemy ORM models inherit from.
Model imports are intentionally NOT here to avoid circular imports.
All models are imported in app/main.py and alembic/env.py instead.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
