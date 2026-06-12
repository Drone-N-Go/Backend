"""Case QR token lifecycle.

Revision ID: 20260612_0005
Revises: 20260612_0004
Create Date: 2026-06-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260612_0005"
down_revision = "20260612_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "case_qr_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, nullable=False),
        sa.Column(
            "drone_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("drones.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("encrypted_token", sa.Text(), nullable=False),
        sa.Column(
            "payload_prefix",
            sa.String(length=255),
            server_default="https://droneandgo.io/case/",
            nullable=False,
        ),
        sa.Column("status", sa.String(length=30), server_default="pending_printed", nullable=False),
        sa.Column(
            "created_by_admin_profile_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("admin_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "confirmed_by_admin_profile_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("admin_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("void_reason", sa.Text(), nullable=True),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending_printed', 'active', 'voided', 'rotated')",
            name="ck_case_qr_tokens_status",
        ),
    )
    op.create_index("ix_case_qr_tokens_drone_id", "case_qr_tokens", ["drone_id"])
    op.create_index("ix_case_qr_tokens_status", "case_qr_tokens", ["status"])
    op.create_index("ix_case_qr_tokens_token_hash", "case_qr_tokens", ["token_hash"], unique=True)
    op.create_index(
        "uq_case_qr_tokens_one_active_per_drone",
        "case_qr_tokens",
        ["drone_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("uq_case_qr_tokens_one_active_per_drone", table_name="case_qr_tokens")
    op.drop_index("ix_case_qr_tokens_token_hash", table_name="case_qr_tokens")
    op.drop_index("ix_case_qr_tokens_status", table_name="case_qr_tokens")
    op.drop_index("ix_case_qr_tokens_drone_id", table_name="case_qr_tokens")
    op.drop_table("case_qr_tokens")
