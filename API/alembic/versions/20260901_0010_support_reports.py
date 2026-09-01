"""Add support_reports table (freeform user issue/damage reports).

Revision ID: 20260901_0010
Revises: 20260714_0009
Create Date: 2026-09-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260901_0010"
down_revision = "20260714_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "support_reports",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("booking_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "image_urls",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="new"),
        sa.Column("admin_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "status IN ('new', 'reviewed', 'resolved')",
            name="ck_support_report_status",
        ),
    )
    op.create_index("ix_support_reports_user_id", "support_reports", ["user_id"])
    op.create_index("ix_support_reports_booking_id", "support_reports", ["booking_id"])


def downgrade() -> None:
    op.drop_index("ix_support_reports_booking_id", table_name="support_reports")
    op.drop_index("ix_support_reports_user_id", table_name="support_reports")
    op.drop_table("support_reports")
