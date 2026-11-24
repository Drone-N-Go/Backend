"""Forgot-password flow: password_reset_codes table + users.password_changed_at.

password_reset_codes holds HMACs of emailed one-time codes (never the codes
themselves). RLS is enabled from the start, like every table since
20260714_0009; access control is enforced in the FastAPI layer.

users.password_changed_at lets the API reject access tokens issued before a
reset, so resetting a password signs the account out on every device.

Revision ID: 20261124_0017
Revises: 20261005_0016
Create Date: 2026-11-24
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20261124_0017"
down_revision = "20261005_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "password_reset_codes",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code_hash", sa.String(length=128), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_password_reset_codes_user_id", "password_reset_codes", ["user_id"])
    op.execute("ALTER TABLE password_reset_codes ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_password_reset_codes_user_id", table_name="password_reset_codes")
    op.drop_table("password_reset_codes")
    op.drop_column("users", "password_changed_at")
