# Developer shortcuts. Everything runs in containers; only Docker is required.
export ESPHEA_UID ?= $(shell id -u)
export ESPHEA_GID ?= $(shell id -g)

NODE_IMAGE := node:22-trixie-slim@sha256:2117f713a417f3aff682ac8f5bc2ebbdf1beed51f36e67ab1e0fd3866b6d2d8f
BACKEND := docker run --rm -u $(ESPHEA_UID):$(ESPHEA_GID) -e HOME=/tmp -v $(CURDIR)/backend:/app -w /app esphea-backend-dev
NODE := docker run --rm -u $(ESPHEA_UID):$(ESPHEA_GID) -e HOME=/tmp -e npm_config_cache=/tmp/.npm -v $(CURDIR)/frontend:/app -w /app $(NODE_IMAGE)

.PHONY: help up down logs ps backend-image backend-check backend-validate backend-format \
        frontend-install frontend-check frontend-format openapi check

help: ## List the available targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-18s %s\n", $$1, $$2}'

up: ## Build and start the whole platform (UI on :8090, API on :8000)
	docker compose up -d --build

down: ## Stop the platform (data is kept)
	docker compose down

logs: ## Follow the logs of the API and the workers
	docker compose logs -f api worker

ps: ## Show the status of the services
	docker compose ps

backend-image: ## Build the backend development image (all dependency groups)
	docker build --target dev -t esphea-backend-dev backend

backend-check: backend-image ## Lint, type-check and run the fast backend tests
	$(BACKEND) sh -c 'ruff check src tests migrations && ruff format --check src tests migrations && mypy && pytest -m "not slow"'

backend-validate: backend-image ## Statistical validation against pymoo's native NSGA-II/III (slow)
	$(BACKEND) pytest -m slow

backend-format: backend-image ## Auto-fix lint issues and format the backend
	$(BACKEND) sh -c 'ruff check --fix src tests migrations && ruff format src tests migrations'

frontend-install: ## Install the locked frontend dependencies
	$(NODE) npm ci --no-audit --no-fund

frontend-check: ## Lint, type-check, test and build the frontend
	$(NODE) sh -c 'npm run lint && npm run format:check && npm run typecheck && npm test && npm run build'

frontend-format: ## Format the frontend
	$(NODE) npm run format

openapi: backend-image ## Regenerate frontend/openapi.json and the TypeScript API types
	$(BACKEND) python -m esphea.api.openapi > frontend/openapi.json
	$(NODE) npm run gen:api

check: backend-check frontend-check ## Run every fast check
