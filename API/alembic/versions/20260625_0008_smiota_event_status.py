"""Add processing status to Smiota event log.

Revision ID: 20260625_0008
Revises: 20260617_0007
Create Date: 2026-06-25
"""

from alembic import op
import sqlalchemy as sa


revision = "20260625_0008"
down_revision = "20260617_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "smiota_events",
        sa.Column(
            "processing_status",
            sa.String(length=30),
            server_default="received",
            nullable=False,
        ),
    )
    op.add_column(
        "smiota_events",
        sa.Column("error_message", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("smiota_events", "error_message")
    op.drop_column("smiota_events", "processing_status")
