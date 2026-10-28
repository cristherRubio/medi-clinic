# medi-clinic

Agenda B2B para clínicas con recordatorios. Especificación completa: [`docs/PROMPT_MAESTRO.md`](docs/PROMPT_MAESTRO.md).

## Estructura

```
backend/   FastAPI (uv, Python 3.13)
  app/       config.py, main.py, crypto/ (cifrado de campos), db/ (motor async y RLS), auth/ (contraseñas, TOTP, tokens)
  alembic/   migraciones (se ejecutan con el rol `migrador`)
  tests/     crypto, auth y db (las de db solo corren en CI)
frontend/  React + TypeScript (Vite)
infra/     docker-compose, db/ (roles y su script de init), scripts/, (Caddy y respaldos más adelante)
docs/      prompt maestro, runbooks, borradores legales
.github/   CI (Postgres 16, roles, migraciones, ruff + pytest + mypy)
Makefile   atajos de desarrollo (`make` muestra la lista)
```

## Requisitos

[uv](https://docs.astral.sh/uv/), Docker con Compose v2, `make` y [pre-commit](https://pre-commit.com/) (`uv tool install pre-commit`).

## Primer arranque

```bash
bash infra/scripts/gen-local-secrets.sh   # crea los secretos en ./secrets (no sobrescribe)
(cd backend && uv sync)                   # instala dependencias desde uv.lock
pre-commit install                        # hook de pre-commit (una vez por clon)
make check                                # ruff + pytest + mypy
make up                                   # levanta db + api con Docker
curl localhost:8000/health                # {"status":"ok"}
```

Si cambian los roles o secretos de la base y ya existía el volumen, hay que recrearlo
(**borra los datos de desarrollo**): `make down` y luego `docker compose -f infra/docker-compose.yml down -v`.

## Comandos

| Comando | Qué hace |
|---|---|
| `make` | muestra la ayuda |
| `make check` | ruff + pytest + mypy (lo que corre el CI) |
| `make format` | formatea y corrige con ruff |
| `make up` / `make down` | levanta (reconstruye) / apaga db + api |

## Pruebas de base de datos

`db` está en una red Docker interna, sin puertos al host, así que **las pruebas de BD corren solo en CI**
(GitHub Actions levanta un Postgres 16, crea los roles y migra). En local se saltan (`skipped`);
se activan con `APP_TEST_DB=1`. Para verificar un cambio de BD: empuja una rama y revisa que el CI esté en verde
y que esas pruebas aparezcan como *passed*.

## Configuración

Nombre y dominio viven solo en `backend/app/config.py` (`APP_NAME_DEFAULT`, `DOMINIO_DEFAULT`)
y se sobrescriben con variables de entorno con prefijo `APP_`:
`APP_APP_NAME`, `APP_DOMINIO`, `APP_ENTORNO`, `APP_SECRETS_DIR`, `APP_KEK_ACTIVE_VERSION`,
`APP_DB_HOST`, `APP_DB_PORT`, `APP_DB_NAME`, `APP_SESSION_IDLE_HOURS`, `APP_SESSION_MAX_HOURS`, `APP_INVITACION_HORAS`.
No hay `.env.example`: los valores por defecto sirven en local y los secretos van en archivos.

## Secretos y cifrado

- Los secretos son **archivos** en `./secrets/` (permisos 600), nunca en git ni en variables de entorno:
  `db_password` (superusuario de Postgres, solo crea los roles), `db_migrador_password`, `db_app_password`,
  `db_operador_password` y `kek_vN`.
- `secrets/kek_vN` es la llave maestra (KEK). **Si se pierde, se pierden todos los datos cifrados:** respáldala aparte y fuera de línea.
- Los datos personales se cifran por campo (AES-256-GCM) con una llave por clínica (DEK), envuelta con la KEK. Ver `backend/app/crypto/` y la sección 8 del prompt maestro.
- Tres roles de BD: `migrador` (dueño de tablas), `app` (la API; RLS aplica) y `operador` (permisos solo sobre `usuario`, `invitacion` y lo mínimo).

## Reglas

Sin datos personales en logs, URLs ni pruebas (ver sección 8 del prompt maestro).