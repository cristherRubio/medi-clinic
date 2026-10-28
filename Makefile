.DEFAULT_GOAL := help
.PHONY: help check format up down

BACK    := cd backend &&
COMPOSE := docker compose -f infra/docker-compose.yml

help: ## Muestra esta ayuda
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  \033[36m%-8s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

check: ## ruff + pytest + mypy (lo que corre el CI)
	$(BACK) uv run ruff check . && uv run ruff format --check . && uv run pytest && uv run mypy

format: ## Formatea y corrige con ruff
	$(BACK) uv run ruff format . && uv run ruff check --fix .

up: ## Levanta db + api con Docker (reconstruye)
	$(COMPOSE) up --build -d

down: ## Apaga los contenedores
	$(COMPOSE) down

migrate: ## Aplica migraciones
	$(COMPOSE) --profile tools run --rm migrate