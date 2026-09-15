"""Add contact_submissions table (public website contact form backstop).

Created with RLS enabled from the start (unlike support_reports, which
needed a follow-up migration in 20260908_0013 because it was added after
the one-time sweep in 20260714_0009 and slipped through) -- access control
for this table is enforced in the FastAPI layer, not via Postgres roles,
same rationale as 20260908_0013.

Revision ID: 20260915_0014
Revises: 20260908_0013
Create Date: 2026-09-15
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260915_0014"
down_revision = "20260908_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contact_submissions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("email_sent", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_contact_submissions_created_at", "contact_submissions", ["created_at"]
    )
    op.execute("ALTER TABLE contact_submissions ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_contact_submissions_created_at", table_name="contact_submissions")
    op.drop_table("contact_submissions")
