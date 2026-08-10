# Fantasy League Analytics — developer commands.
# Backend runs in backend/.venv for local (non-Docker) work.

PY := backend/.venv/bin/python
PIP := backend/.venv/bin/pip
PYTEST := backend/.venv/bin/pytest
RUFF := backend/.venv/bin/ruff
MYPY := backend/.venv/bin/mypy

.PHONY: help
help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# --- Local backend (venv) ---
.PHONY: venv
venv: ## Create backend venv and install deps
	python3 -m venv backend/.venv
	$(PIP) install -r backend/requirements.txt

.PHONY: migrate
migrate: ## Apply database migrations
	cd backend && .venv/bin/python manage.py migrate

.PHONY: runserver
runserver: ## Run the Django dev server
	cd backend && .venv/bin/python manage.py runserver

.PHONY: fixtures
fixtures: ## Load the synthetic multi-season fixture league
	cd backend && .venv/bin/python manage.py load_fixtures

.PHONY: demo-data
demo-data: ## Load fixtures + synthetic ADP + compute analytics (full demo)
	cd backend && .venv/bin/python manage.py migrate
	cd backend && .venv/bin/python manage.py load_fixtures --reset
	cd backend && .venv/bin/python manage.py sync_nfl_context --source synthetic --league-id 999999
	cd backend && .venv/bin/python manage.py compute_analytics --league-id 999999

.PHONY: sync
sync: ## Full ESPN + NFL sync then recompute analytics (needs .env creds)
	cd backend && .venv/bin/python manage.py full_sync

# --- Quality gates ---
.PHONY: test
test: ## Run backend tests
	cd backend && .venv/bin/pytest -q

.PHONY: lint
lint: ## Ruff lint + format check
	cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .

.PHONY: typecheck
typecheck: ## mypy type check
	cd backend && .venv/bin/mypy league config

.PHONY: secret-scan
secret-scan: ## Fail if tracked files contain credentials
	./scripts/check_secrets.sh

.PHONY: check
check: secret-scan lint typecheck test ## Run all backend quality gates

# --- Frontend ---
.PHONY: frontend-install
frontend-install: ## Install frontend deps
	cd frontend && npm install

.PHONY: frontend-test
frontend-test: ## Run frontend unit tests
	cd frontend && npm run test

.PHONY: frontend-build
frontend-build: ## Type-check and build the frontend
	cd frontend && npm run build

.PHONY: frontend-e2e
frontend-e2e: ## Run Playwright e2e (needs backend+frontend running with demo-data)
	cd frontend && npm run test:e2e

# --- Docker ---
.PHONY: dev
dev: ## Bring up the full local stack (Postgres + backend + frontend)
	docker compose up --build

.PHONY: down
down: ## Stop the local stack
	docker compose down
