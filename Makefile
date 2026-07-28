# Data-collection back office — the commands you actually run.
#
# Everything goes through `uv run`, so there is no venv to activate and no drift between what you
# type and what CI types. `make` with no target prints this list.

UV      ?= uv
MANAGE  := $(UV) run python src/manage.py
COMPOSE ?= docker compose

# `.env` sets COMPOSE_FILE=docker/compose.yaml, which is what lets plain `docker compose` find
# the file from the repository root.

.DEFAULT_GOAL := help
.PHONY: help install env check migrations migrate seed collectors run worker scheduler tick \
        shell superuser test test-unit lint fmt contracts verify \
        up down restart build logs ps db docker-migrate docker-seed docker-shell clean reset-db

## ----------------------------------------------------------------- setup

help:  ## Show this list
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install:  ## Sync dependencies and install the project (editable)
	$(UV) sync

env:  ## Create .env from .env.example if it is missing
	@test -f .env || (cp .env.example .env && echo "created .env from .env.example")
	@test -f .env && echo ".env is present"

## ----------------------------------------------------------------- app

migrations:  ## Generate migrations for changed models
	$(MANAGE) makemigrations

migrate:  ## Apply migrations
	$(MANAGE) migrate

seed:  ## Dev data: admin/admin superuser, collector projection, sample configs (idempotent)
	$(MANAGE) seed

collectors:  ## Sync the Collector projection from collector code (run on deploy)
	$(MANAGE) sync_collectors

run:  ## Start the development server on :8000
	$(MANAGE) runserver 0.0.0.0:8000

worker:  ## Start a worker. Run several — they compete for rows
	$(MANAGE) run_worker

scheduler:  ## Start the scheduler loop
	$(MANAGE) run_scheduler --loop

tick:  ## One scheduling pass, then exit (what cron would run)
	$(MANAGE) run_scheduler

shell:  ## Django shell
	$(MANAGE) shell

superuser:  ## Create a superuser interactively
	$(MANAGE) createsuperuser

## ----------------------------------------------------------------- quality

test:  ## Run the test suite
	$(UV) run pytest

test-unit:  ## Run only the pure tests (no database)
	$(UV) run pytest tests/unit

lint:  ## Ruff check + format check
	$(UV) run ruff check .
	$(UV) run ruff format --check .

fmt:  ## Apply ruff fixes and formatting
	$(UV) run ruff check . --fix
	$(UV) run ruff format .

contracts:  ## Verify the import-linter dependency contracts (§13)
	$(UV) run lint-imports

check:  ## Django system check + migration drift
	$(MANAGE) check
	$(MANAGE) makemigrations --check --dry-run

verify: check lint contracts test  ## The full definition of done (§15)
	@echo "all green"

## ----------------------------------------------------------------- docker

build:  ## Build the application image
	$(COMPOSE) build

up:  ## Start db, web, worker and scheduler
	$(COMPOSE) up -d
	@echo "web on http://localhost:8000 — admin/admin after 'make docker-seed'"

db:  ## Start Postgres only (for local development against it)
	$(COMPOSE) up -d db

down:  ## Stop the stack (the database volume survives)
	$(COMPOSE) down

restart:  ## Recreate the stack from a fresh build
	$(COMPOSE) up -d --build

logs:  ## Follow logs from every service
	$(COMPOSE) logs -f

ps:  ## Show service status
	$(COMPOSE) ps

docker-migrate:  ## Apply migrations inside the web container
	$(COMPOSE) exec web python src/manage.py migrate

docker-seed:  ## Seed dev data inside the web container
	$(COMPOSE) exec web python src/manage.py seed

docker-shell:  ## Shell inside the web container
	$(COMPOSE) exec web bash

## ----------------------------------------------------------------- housekeeping

clean:  ## Remove caches and build leftovers
	rm -rf .pytest_cache .ruff_cache .import_linter_cache staticfiles
	find . -type d -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true

reset-db:  ## Drop the database volume and start over. DESTRUCTIVE
	$(COMPOSE) down -v
	$(COMPOSE) up -d db
	@echo "volume dropped — run 'make migrate seed' once Postgres is up"
