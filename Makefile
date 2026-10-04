# OpsPilot developer commands. Local Postgres 16 + pgvector must be running (or `docker compose up db`).
API := api
PY := $(API)/.venv/bin/python
SCRATCH_ENV := set -a && . ./.env && set +a

.PHONY: setup db-roles migrate seed api worker web test test-live lint client check

setup:
	cd $(API) && python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
	cd web && npm install

# Least-privilege application role used by api, worker and web (row-level security applies to it).
db-roles:
	psql -d postgres -c "DO \$$\$$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='opspilot_app') THEN CREATE ROLE opspilot_app LOGIN PASSWORD 'opspilot_app' NOSUPERUSER NOBYPASSRLS; END IF; END \$$\$$;"

migrate:
	cd $(API) && $(SCRATCH_ENV) && .venv/bin/alembic upgrade head

# Rebuild the schema and seed both demo organisations (120 days) plus the demo invoice files.
seed:
	cd $(API) && $(SCRATCH_ENV) && PYTHONPATH=. .venv/bin/python -m app.seed --reset

api:
	cd $(API) && .venv/bin/uvicorn app.main:app --port 8000 --reload --reload-dir app --env-file .env

worker:
	cd $(API) && $(SCRATCH_ENV) && PYTHONPATH=. .venv/bin/procrastinate --app=app.workers.app.app worker

web:
	cd web && npm run dev

test:
	cd $(API) && .venv/bin/python -m pytest -q

# Golden documents against the live Gemini API (uses free-tier quota; paced for rate limits).
test-live:
	cd $(API) && $(SCRATCH_ENV) && OPSPILOT_LIVE_AI=1 .venv/bin/python -m pytest -q tests/golden

lint:
	cd $(API) && .venv/bin/ruff check app tests && .venv/bin/pyright && .venv/bin/lint-imports
	cd web && npm run lint && npm run typecheck

# Regenerate the typed frontend client from the API's OpenAPI 3.1 schema (FR-API-01).
client:
	cd $(API) && .venv/bin/python -c "import json; from app.main import create_app; print(json.dumps(create_app().openapi(), indent=1))" > ../web/lib/api/openapi.json
	cd web && npm run api:types

check: lint test
