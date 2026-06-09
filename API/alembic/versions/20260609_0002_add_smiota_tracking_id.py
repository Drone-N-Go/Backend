"""Add tracking ID to Smiota event log.

Revision ID: 20260609_0002
Revises: 20260609_0001
Create Date: 2026-06-09
"""

from alembic import op
import sqlalchemy as sa


revision = "20260609_0002"
down_revision = "20260609_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "smiota_events",
        sa.Column("tracking_id", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("smiota_events", "tracking_id")
