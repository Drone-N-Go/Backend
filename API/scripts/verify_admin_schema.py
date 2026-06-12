#!/usr/bin/env python3
"""Fail fast when the deployed database is missing admin-backend schema."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db.startup import EXPECTED_ADMIN_REVISION, verify_admin_schema


def main() -> int:
    try:
        asyncio.run(verify_admin_schema())
        print(f"Admin schema verified at Alembic revision {EXPECTED_ADMIN_REVISION}.")
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
