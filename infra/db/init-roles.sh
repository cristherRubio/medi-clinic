#!/bin/sh
# Lee las contraseñas de los secretos y ejecuta roles.sql.
# En Docker usa los valores por defecto; en CI se sobrescriben con variables de entorno.
set -eu

SECRETS="${SECRETS_DIR:-/run/secrets}"
SQL="${ROLES_SQL:-/opt/roles.sql}"

psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -v dbname="$POSTGRES_DB" \
  -v migrador_pw="$(cat "$SECRETS/db_migrador_password")" \
  -v app_pw="$(cat "$SECRETS/db_app_password")" \
  -v operador_pw="$(cat "$SECRETS/db_operador_password")" \
  -f "$SQL"