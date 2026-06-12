#!/usr/bin/env bash
set -euo pipefail

echo "Alembic revision before migration:"
alembic current || true

alembic upgrade head

echo "Alembic revision after migration:"
alembic current

python scripts/verify_admin_schema.py

uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
