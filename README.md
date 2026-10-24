# medi-clinic

Agenda B2B para clínicas con recordatorios. Especificación completa: [`docs/PROMPT_MAESTRO.md`](docs/PROMPT_MAESTRO.md).

## Estructura

```
backend/   FastAPI (uv, Python 3.13)
  app/       config.py, main.py, crypto/ (cifrado de campos)
  tests/
frontend/  React + TypeScript (Vite)
infra/     docker-compose, scripts, (Caddy y respaldos más adelante)
docs/      prompt maestro, runbooks, borradores legales
Makefile   atajos de desarrollo (`make` muestra la lista)
```

## Requisitos

[uv](https://docs.astral.sh/uv/), Docker con Compose v2, `make` y [pre-commit](https://pre-commit.com/) (`uv tool install pre-commit`).

## Primer arranque

```bash
make secrets                 # crea secrets/db_password y secrets/kek_v1 (no se suben a git)
(cd backend && uv sync)      # instala dependencias desde uv.lock
make hooks                   # instala el hook de pre-commit (una vez por clon)
make check                   # pruebas + ruff + mypy
make up                      # levanta db + api con Docker
curl localhost:8000/health   # {"status":"ok"}
```

## Comandos

| Comando | Qué hace |
|---|---|
| `make check` | pruebas + ruff + mypy |
| `make test` / `lint` / `typecheck` | cada chequeo por separado |
| `make format` | formatea y corrige con ruff |
| `make up` / `down` / `logs` / `ps` | contenedores (db + api) |
| `make secrets` | genera secretos locales sin sobrescribir los existentes |
| `make hooks` / `precommit` | instala pre-commit / lo corre sobre todos los archivos |

Pre-commit corre ruff, mypy y gitleaks en cada `git commit`; `gitleaks` descarga su propio binario.

## Configuración

Nombre y dominio viven solo en `backend/app/config.py` (`APP_NAME_DEFAULT`, `DOMINIO_DEFAULT`)
y se sobrescriben con variables de entorno (ver `.env.example`):
`APP_APP_NAME`, `APP_DOMINIO`, `APP_ENTORNO`, `APP_SECRETS_DIR`, `APP_KEK_ACTIVE_VERSION`.

## Secretos y cifrado

- Los secretos son **archivos** en `./secrets/` (permisos 600), nunca en git ni en variables de entorno.
- `secrets/kek_vN` es la llave maestra (KEK). **Si se pierde, se pierden todos los datos cifrados:** respáldala aparte y fuera de línea.
- Los datos personales se cifran por campo (AES-256-GCM) con una llave por clínica (DEK), envuelta con la KEK. Ver `backend/app/crypto/` y la sección 8 del prompt maestro.

## Reglas

Sin datos personales en logs, URLs ni pruebas (ver sección 8 del prompt maestro).