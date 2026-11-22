.DEFAULT_GOAL := help
.PHONY: help check check-db format up down migrate auditoria

BACK    := cd backend &&
COMPOSE := docker compose -f infra/docker-compose.yml

help: ## Muestra esta ayuda
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  \033[36m%-8s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

check: ## ruff + pytest + mypy (lo que corre el CI)
	$(BACK) uv run ruff check . && uv run ruff format --check . && uv run pytest && uv run mypy

check-db: ## Todas las pruebas, también las de BD, con un Postgres temporal (antes de empujar)
	bash infra/scripts/check-db.sh

format: ## Formatea y corrige con ruff
	$(BACK) uv run ruff format . && uv run ruff check --fix .

up: ## Levanta db + api con Docker (reconstruye)
	$(COMPOSE) up --build -d

down: ## Apaga los contenedores
	$(COMPOSE) down

migrate: ## Aplica migraciones
	$(COMPOSE) --profile tools run --rm migrate

auditoria: ## Últimos eventos de auditoría de la BD local (N=50); sin datos personales
	$(COMPOSE) exec -T db sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -c "SELECT creado_en, clinica_id, actor_usuario_id, accion, entidad, entidad_id, metadata FROM auditoria ORDER BY creado_en DESC LIMIT $(or $(N),50)"'
