# medi-clinic

Agenda web para clínicas y consultorios pequeños, con recordatorios de citas y datos de pacientes cifrados.

> Nombre y dominio provisionales. Se cambian en `backend/app/config.py`.

## Estructura

```
backend/   API (FastAPI, Python 3.13, uv)
frontend/  Interfaz (React + TypeScript), pendiente
infra/     Docker Compose, roles de la base de datos y script de secretos locales
docs/      Documentación del proyecto
.github/   CI y Dependabot
Makefile   Atajos de desarrollo (`make` muestra la lista)
```

## Requisitos

[uv](https://docs.astral.sh/uv/), Docker con Compose v2, `make` y [pre-commit](https://pre-commit.com/) (`uv tool install pre-commit`).

## Primer arranque

```bash
bash infra/scripts/gen-local-secrets.sh   # crea los secretos en ./secrets (no sobrescribe)
(cd backend && uv sync)                   # instala dependencias
pre-commit install                        # una vez por clon
make check                                # ruff + pytest + mypy
make up                                   # levanta base de datos y API
make migrate                              # aplica las migraciones
docker compose -f infra/docker-compose.yml --profile tools run --rm bootstrap   # crea el primer operador
curl localhost:8000/health                # {"status":"ok"}
```

### Primer operador

El operador es el dueño de la plataforma: crea clínicas e invita a sus administradores. No ve datos de pacientes.

El script pide email y contraseña (12 a 128 caracteres) y muestra un secreto para tu app de autenticación:

1. En la app (Google Authenticator, Aegis…) elige "ingresar clave manualmente", pega el secreto y deja tipo basado en tiempo (6 dígitos, 30 s).
2. Escribe en el script el código de 6 dígitos que muestre la app.
3. Guarda los 10 códigos de recuperación: se muestran una sola vez.

Si el script falla antes de terminar no se guarda nada; borra esa entrada del autenticador y vuelve a correrlo (genera un secreto nuevo cada vez). Solo puede ejecutarse una vez por base de datos.

### Empezar de cero

Borra los datos de desarrollo:

```bash
docker compose -f infra/docker-compose.yml down -v
make up
make migrate
docker compose -f infra/docker-compose.yml --profile tools run --rm bootstrap
```

Los roles de la base de datos se crean solo cuando el volumen está vacío. Si regeneras los secretos, hay que borrar el volumen con `down -v`; si no, la API no podrá conectarse.

## Comandos

| Comando | Qué hace |
|---|---|
| `make` | muestra la ayuda |
| `make check` | ruff + pytest + mypy (lo mismo que corre el CI) |
| `make format` | formatea y corrige con ruff |
| `make up` / `make down` | levanta (reconstruyendo) / apaga base de datos y API |
| `make migrate` | aplica las migraciones |

## Pruebas

La base de datos está en una red interna de Docker, sin puertos hacia tu máquina, así que las pruebas que la usan **solo corren en CI** (GitHub Actions). En local aparecen como `skipped`. Para verificar un cambio de base de datos, sube una rama y revisa que el CI esté en verde y que esas pruebas salgan como `passed`.

## CI

Tres jobs en `.github/workflows/ci.yml`:

- **backend:** Postgres 16, migraciones, `make check` y `pip-audit` sobre las dependencias.
- **secretos:** gitleaks sobre todo el historial.
- **imagen:** construye la imagen del backend y la escanea con Trivy.

Dependabot abre PRs semanales (Python, Docker y GitHub Actions). Fusiónalos solo con el CI en verde.

## Secretos

Son archivos en `./secrets/`, ignorados por git. Nunca van en variables de entorno.

| Archivo | Uso |
|---|---|
| `db_password` | Superusuario de Postgres; solo crea los roles al iniciar |
| `db_migrador_password` | Rol dueño de las tablas (migraciones y bootstrap) |
| `db_app_password` | Rol de la API |
| `db_operador_password` | Rol del operador |
| `kek_v1` | Llave maestra de cifrado |

**Si pierdes `kek_vN` pierdes todos los datos cifrados.** Respáldala aparte y fuera de línea.

En desarrollo los archivos quedan con permisos 644 dentro de una carpeta 700, porque Docker Compose no cambia el dueño al montarlos y el contenedor debe poder leerlos. En producción se resuelve de otra forma.

## Configuración

Las opciones se sobrescriben con variables de entorno con prefijo `APP_` (por ejemplo `APP_ENTORNO`, `APP_DB_HOST`, `APP_SECRETS_DIR`). Los valores por defecto sirven en local; la lista completa está en `backend/app/config.py`.

## Correo en desarrollo

Se usa Resend por su API, sin dominio propio: crea una cuenta, guarda la API key en `secrets/resend_api_key` y usa el remitente de pruebas de Resend, que solo entrega al correo del dueño de la cuenta. Las pruebas automáticas usan un cliente simulado.

## Privacidad

Los datos personales nunca se guardan en claro, ni aparecen en logs, URLs o pruebas.