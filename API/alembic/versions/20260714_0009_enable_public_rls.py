"""Enable RLS on public schema tables.

Revision ID: 20260714_0009
Revises: 20260625_0008
Create Date: 2026-07-14
"""

from alembic import op
from sqlalchemy import text


revision = "20260714_0009"
down_revision = "20260625_0008"
branch_labels = None
depends_on = None


TABLES_WITH_RLS_DISABLED = """
SELECT format('%I.%I', n.nspname, c.relname) AS qualified_name
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relkind IN ('r', 'p')
  AND c.relrowsecurity = false
ORDER BY n.nspname, c.relname;
"""


def _tables_with_rls_disabled(connection) -> list[str]:
    result = connection.execute(text(TABLES_WITH_RLS_DISABLED))
    return list(result.scalars())


def upgrade() -> None:
    connection = op.get_bind()
    tables = _tables_with_rls_disabled(connection)

    if not tables:
        print("All public tables already have Row Level Security enabled.")
    else:
        print("Enabling Row Level Security on public tables:")
        for table in tables:
            connection.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
            print(f"  ok: {table}")

    remaining = _tables_with_rls_disabled(connection)
    if remaining:
        missing = ", ".join(remaining)
        raise RuntimeError(
            "Public tables still missing Row Level Security after migration: "
            f"{missing}"
        )

    print("Verification passed: every public table has Row Level Security enabled.")


def downgrade() -> None:
    # Intentionally no-op: disabling RLS would reopen Supabase's
    # rls_disabled_in_public security finding.
    print("RLS remains enabled on public tables; downgrade is intentionally no-op.")
