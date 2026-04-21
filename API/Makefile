# =============================================================================
# Drone N' Go API — Makefile
# =============================================================================
# Usage:
#   make install       Install Python dependencies
#   make dev           Run the dev server (hot reload)
#   make migrate       Apply all pending Alembic migrations
#   make revision      Generate a new Alembic migration (MSG="description")
#   make downgrade     Roll back the last migration
#   make freeze        Pin current installed packages to requirements.txt
# =============================================================================

.PHONY: install dev migrate revision downgrade freeze

install:
	pip install -r requirements.txt

dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

migrate:
	alembic upgrade head

revision:
	@read -p "Migration message: " msg; \
	alembic revision --autogenerate -m "$$msg"

downgrade:
	alembic downgrade -1

freeze:
	pip freeze > requirements.txt
