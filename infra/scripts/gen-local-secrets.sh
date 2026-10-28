#!/usr/bin/env bash
# Genera secretos LOCALES de desarrollo en ./secrets (ignorado por git). No imprime valores.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DIR="$ROOT/secrets"

umask 077
mkdir -p "$DIR"
chmod 700 "$DIR"

# gen <archivo> <comando generador>
gen() {
  if [[ -f "$DIR/$1" ]]; then
    echo "secrets/$1 ya existe; no se sobrescribe."
  else
   bash -c "$2" | tr -d '\n' > "$DIR/$1"
    chmod 644 "$DIR/$1"
    echo "secrets/$1 creado (permisos 644; la carpeta es 700)."
  fi
}

# Superusuario de Postgres: solo crea los roles al iniciar la base.
gen db_password "openssl rand -hex 24"

# Roles de la aplicación (sección 8.3).
gen db_migrador_password "openssl rand -hex 24"
gen db_app_password "openssl rand -hex 24"
gen db_operador_password "openssl rand -hex 24"

# KEK local de desarrollo (32 bytes en base64). En producción se genera aparte y se respalda
# fuera de línea: perderla significa perder todos los datos.
gen kek_v1 "openssl rand -base64 32"