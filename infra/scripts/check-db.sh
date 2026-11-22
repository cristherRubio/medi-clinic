#!/usr/bin/env bash
# Corre TODAS las pruebas (incluidas las de BD) contra un Postgres 16 temporal, como el CI.
# El contenedor se borra al terminar (también si algo falla). No toca la BD de `make up`.
# Uso: make check-db  [PUERTO=55432] [ARGS="tests/api/test_agenda.py -x"]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PUERTO="${PUERTO:-55432}"
NOMBRE="medi-check-db-$$"
SUPER_PASS="$(openssl rand -hex 16)"  # solo vive mientras dura el contenedor

if [[ ! -f "$ROOT/secrets/kek_v1" ]]; then
  echo "Faltan secretos locales: corre infra/scripts/gen-local-secrets.sh" >&2
  exit 1
fi

limpiar() { docker stop "$NOMBRE" >/dev/null 2>&1 || true; }
trap limpiar EXIT

echo "Levantando Postgres 16 temporal en 127.0.0.1:$PUERTO..."
docker run -d --rm --name "$NOMBRE" \
  -e POSTGRES_USER=medi_admin -e POSTGRES_PASSWORD="$SUPER_PASS" -e POSTGRES_DB=medi_clinic \
  -p "127.0.0.1:$PUERTO:5432" postgres:16 >/dev/null

for _ in $(seq 60); do
  docker exec "$NOMBRE" pg_isready -U medi_admin -d medi_clinic -h 127.0.0.1 >/dev/null 2>&1 && break
  sleep 1
done

echo "Creando roles..."
PGHOST=127.0.0.1 PGPORT="$PUERTO" PGPASSWORD="$SUPER_PASS" \
  POSTGRES_USER=medi_admin POSTGRES_DB=medi_clinic \
  SECRETS_DIR="$ROOT/secrets" ROLES_SQL="$ROOT/infra/db/roles.sql" \
  bash "$ROOT/infra/db/init-roles.sh" >/dev/null

cd "$ROOT/backend"
export APP_DB_HOST=127.0.0.1 APP_DB_PORT="$PUERTO" APP_SECRETS_DIR="$ROOT/secrets"

echo "Migraciones..."
uv run alembic upgrade head 2>&1 | tail -1

echo "Pruebas..."
# shellcheck disable=SC2086  # ARGS se separa a propósito
APP_TEST_DB=1 uv run pytest -p no:warnings ${ARGS:-}
