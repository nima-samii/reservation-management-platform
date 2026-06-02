# ══════════════════════════════════════════════════════════════════════════════
#  19-Step Reservation Bot — Makefile
#  Usage: make <target>   |   make help  (shows all targets)
# ══════════════════════════════════════════════════════════════════════════════

# ── Shell & Python path detection ─────────────────────────────────────────────
ifeq ($(OS),Windows_NT)
    PYTHON := .venv/Scripts/python
    PIP    := .venv/Scripts/pip
else
    PYTHON := .venv/bin/python
    PIP    := .venv/bin/pip
endif

# ── Docker Compose shortcuts ──────────────────────────────────────────────────
DC       := docker compose
DC_DEV   := docker compose -f docker-compose.yml -f docker-compose.dev.yml
DC_ADMIN := docker compose -f docker-compose.admin.yml

# ── Container names (project dir = 19-step → prefix = 19-step) ───────────────
APP_CTR   := 19-step-app-1
DB_CTR    := 19-step-db-1
REDIS_CTR := 19-step-redis-1

# ── Default target ────────────────────────────────────────────────────────────
.DEFAULT_GOAL := help

.PHONY: help \
        up build dev down down-v restart ps logs logs-all \
        admin-up admin-down admin-rebuild admin-logs \
        migrate migrate-local migration migrate-down migrate-history \
        seed seed-local db-shell db-logs \
        install run run-api \
        admin-install admin-dev admin-build \
        test test-fast test-cov \
        redis-shell redis-keys redis-flush \
        hash gen-secret \
        clean setup


# ══════════════════════════════════════════════════════════════════════════════
#  HELP
# ══════════════════════════════════════════════════════════════════════════════

help: ## Show this help message
	@echo ""
	@echo "  19-Step Reservation Bot"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'
	@echo ""


# ══════════════════════════════════════════════════════════════════════════════
#  DOCKER — MAIN STACK (bot + db + redis)
# ══════════════════════════════════════════════════════════════════════════════

up: ## Start production stack detached (webhook mode)
	$(DC) up -d

build: ## Rebuild images and start production stack
	$(DC) up --build -d

dev: ## Start dev stack — polling mode + hot-reload (foreground)
	$(DC_DEV) up --build

down: ## Stop all main-stack services
	$(DC) down

down-v: ## Stop services and DELETE volumes  ⚠ destroys DB data
	@echo "WARNING: This will delete all database and redis data."
	@read -p "Are you sure? [y/N] " ans && [ "$$ans" = "y" ]
	$(DC) down -v

restart: ## Restart only the app container
	$(DC) restart app

ps: ## Show running container status
	$(DC) ps

logs: ## Follow app container logs (Ctrl+C to exit)
	$(DC) logs -f app

logs-all: ## Follow ALL service logs
	$(DC) logs -f


# ══════════════════════════════════════════════════════════════════════════════
#  DOCKER — ADMIN PANEL (Next.js on port 3000)
# ══════════════════════════════════════════════════════════════════════════════

admin-up: ## Build and start admin panel
	$(DC_ADMIN) up --build -d

admin-down: ## Stop admin panel
	$(DC_ADMIN) down

admin-rebuild: ## Force-rebuild admin panel (clears Docker cache)
	$(DC_ADMIN) build --no-cache
	$(DC_ADMIN) up -d

admin-logs: ## Follow admin panel logs
	$(DC_ADMIN) logs -f


# ══════════════════════════════════════════════════════════════════════════════
#  DATABASE & MIGRATIONS
# ══════════════════════════════════════════════════════════════════════════════

migrate: ## Apply all pending migrations  (runs inside app container)
	$(DC) exec app alembic upgrade head

migrate-local: ## Apply all pending migrations  (local venv)
	$(PYTHON) -m alembic upgrade head

migration: ## Create a new migration  →  make migration name=add_users_table
	$(PYTHON) -m alembic revision --autogenerate -m "$(name)"

migrate-down: ## Roll back one migration  (local venv)
	$(PYTHON) -m alembic downgrade -1

migrate-history: ## Show full migration history
	$(PYTHON) -m alembic history --verbose

seed: ## Seed country data  (runs inside app container)
	$(DC) exec app python scripts/seed_countries.py

seed-local: ## Seed country data  (local venv)
	$(PYTHON) scripts/seed_countries.py

db-shell: ## Open psql shell inside the DB container
	docker exec -it $(DB_CTR) psql -U postgres -d reservations

db-logs: ## Follow DB container logs
	$(DC) logs -f db


# ══════════════════════════════════════════════════════════════════════════════
#  LOCAL DEVELOPMENT (no Docker)
# ══════════════════════════════════════════════════════════════════════════════

install: ## Install Python deps into .venv
	$(PIP) install -r requirements.txt

run: ## Run bot in polling mode  (local venv, needs DB + Redis running)
	$(PYTHON) main_polling.py

run-api: ## Run FastAPI only with uvicorn --reload  (no bot / scheduler)
	$(PYTHON) -m uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --reload


# ══════════════════════════════════════════════════════════════════════════════
#  ADMIN PANEL — LOCAL (Next.js)
# ══════════════════════════════════════════════════════════════════════════════

admin-install: ## npm install inside admin-panel/
	cd admin-panel && npm install

admin-dev: ## Start Next.js dev server on localhost:3000
	cd admin-panel && npm run dev

admin-build: ## Build Next.js production bundle locally
	cd admin-panel && npm run build


# ══════════════════════════════════════════════════════════════════════════════
#  TESTS
# ══════════════════════════════════════════════════════════════════════════════

test: ## Run full test suite  (verbose)
	$(PYTHON) -m pytest tests/ -v

test-fast: ## Run tests without verbose output
	$(PYTHON) -m pytest tests/

test-cov: ## Run tests with coverage report
	$(PYTHON) -m pytest tests/ -v --cov=app --cov-report=term-missing


# ══════════════════════════════════════════════════════════════════════════════
#  REDIS
# ══════════════════════════════════════════════════════════════════════════════

redis-shell: ## Open redis-cli interactive shell
	docker exec -it $(REDIS_CTR) redis-cli

redis-keys: ## List all admin refresh-token keys in Redis
	docker exec $(REDIS_CTR) redis-cli KEYS "admin:rt:*"

redis-flush: ## FLUSH ALL Redis data  ⚠ irreversible
	@echo "WARNING: This will delete ALL Redis data (locks, rate limits, tokens)."
	@read -p "Are you sure? [y/N] " ans && [ "$$ans" = "y" ]
	docker exec $(REDIS_CTR) redis-cli FLUSHALL


# ══════════════════════════════════════════════════════════════════════════════
#  SECRETS & UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

hash: ## Generate bcrypt hash for ADMIN_PASSWORD  →  make hash pw=mypassword
	@python -c "import bcrypt; print(bcrypt.hashpw('$(pw)'.encode(), bcrypt.gensalt(12)).decode())"

gen-secret: ## Generate a 64-char random hex string for ADMIN_JWT_SECRET / WEBHOOK_SECRET
	@python -c "import secrets; print(secrets.token_hex(32))"


# ══════════════════════════════════════════════════════════════════════════════
#  CLEANUP
# ══════════════════════════════════════════════════════════════════════════════

clean: ## Remove Python cache files (__pycache__, *.pyc, .pytest_cache)
	python -c "\
import shutil, pathlib; \
[shutil.rmtree(str(p), ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__')]; \
[shutil.rmtree(str(p), ignore_errors=True) for p in pathlib.Path('.').rglob('.pytest_cache')]; \
[p.unlink(missing_ok=True) for p in pathlib.Path('.').rglob('*.pyc')]; \
print('Cache cleared.')"


# ══════════════════════════════════════════════════════════════════════════════
#  FIRST-TIME SETUP
# ══════════════════════════════════════════════════════════════════════════════

setup: ## One-time setup: copy .env, install deps, run migrations, seed DB
	@test -f .env || (cp .env.example .env && echo ">>> .env created — fill in BOT_TOKEN, POSTGRES_PASSWORD, ADMIN_PASSWORD, ADMIN_JWT_SECRET before continuing <<<")
	@test -d admin-panel/node_modules || (cd admin-panel && npm install)
	$(PIP) install -r requirements.txt
	$(PYTHON) -m alembic upgrade head
	$(PYTHON) scripts/seed_countries.py
	@echo ""
	@echo "Setup complete."
	@echo "  Bot (Docker):        make build"
	@echo "  Bot (local):         make run"
	@echo "  Admin panel (Docker):make admin-up"
	@echo "  Admin panel (local): make admin-dev"
	@echo ""
