# medi-clinic

Agenda B2B para clínicas con recordatorios. Especificación completa: [`docs/PROMPT_MAESTRO.md`](docs/PROMPT_MAESTRO.md).

## Estructura

```
backend/   FastAPI (uv, Python 3.13)
frontend/  React + TypeScript (Vite)
infra/     docker-compose, Caddy, respaldos
docs/      prompt maestro, runbooks, borradores legales
```

## Arranque del backend

```bash
cd backend
uv python pin 3.13
uv add fastapi pydantic-settings
uv add --dev ruff mypy pytest
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

## Pre-commit

```bash
uv tool install pre-commit
pre-commit install
pre-commit run --all-files
```

`gitleaks` lo ejecuta pre-commit (descarga su propio binario).

## Configuración

Nombre y dominio viven solo en `backend/app/config.py` (`APP_NAME_DEFAULT`, `DOMINIO_DEFAULT`)
y se sobrescriben con `APP_APP_NAME` / `APP_DOMINIO`. Secretos: archivos en `./secrets/`, nunca en git.

## Reglas

Sin datos personales en logs, URLs ni pruebas (ver sección 8 del prompt maestro).
