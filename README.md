# medi-clinic

Agenda web para clínicas y consultorios pequeños, con recordatorios de citas y datos de pacientes cifrados.

> Nombre y dominio provisionales. Se cambian en `backend/app/config.py`.

## Estructura

```
backend/   API (FastAPI, Python 3.13, uv)
frontend/  Interfaz (React + TypeScript), pendiente
infra/     Docker Compose, roles de la base de datos y script de secretos locales
docs/      Documentación histórica (prompts); el estado vigente está en CLAUDE.md
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

### Alta de una clínica y su personal

Mientras no exista el frontend, esto se hace por la API (documentación interactiva en `localhost:8000/docs`, solo en local). Las invitaciones **todavía no se envían por correo**: la API devuelve el token una sola vez y quien invita manda el enlace a mano.

1. El operador inicia sesión (`/api/auth/login` y `/api/auth/login/totp`) y crea la clínica con `POST /api/operador/clinicas`. La respuesta trae el token de invitación del admin.
2. El admin activa su cuenta con ese token (`/api/auth/activar/iniciar` y `/confirmar`): fija contraseña, configura TOTP y acepta términos.
3. Admin o asistente invitan a médicos y asistentes con `POST /api/personal/invitaciones`. Los médicos activos más las invitaciones de médico pendientes cuentan para el tope del plan.
4. Si alguien ya tiene cuenta en otra clínica, inicia sesión y acepta con `POST /api/auth/activar/aceptar`.
5. Tras el login, cada persona elige clínica: `GET /api/auth/contextos` y `POST /api/auth/contexto`.

Las invitaciones duran 72 h; el operador puede revocarlas o extenderlas desde `/api/operador/invitaciones/{id}/...`. Suspender una clínica (`PATCH /api/operador/clinicas/{id}` con `estado`) cierra sus sesiones y conserva los datos. Los recordatorios por API de WhatsApp se activan por clínica con `notificaciones_whatsapp` (Fase 2).

## Comandos

| Comando | Qué hace |
|---|---|
| `make` | muestra la ayuda |
| `make check` | ruff + pytest + mypy (lo mismo que corre el CI) |
| `make check-db` | todas las pruebas, incluidas las de base de datos, con un Postgres temporal |
| `make format` | formatea y corrige con ruff |
| `make up` / `make down` | levanta (reconstruyendo) / apaga base de datos y API |
| `make migrate` | aplica las migraciones |
| `make auditoria` | últimos eventos de auditoría de la base local (`N=50` para cambiar cuántos) |

## Pruebas

La base de datos de `make up` está en una red interna de Docker, sin puertos hacia tu máquina, así que `make check` salta las pruebas que la usan (aparecen como `skipped`).

`make check-db` las corre todas contra un Postgres 16 temporal (crea los roles, aplica las migraciones y lo borra al terminar, también si algo falla); no toca tu base de `make up`. Úsalo antes de empujar un cambio de base de datos. Para correr solo una parte: `make check-db ARGS="tests/api/test_agenda.py -x"`. El CI las vuelve a correr en cada push a `main`.

## CI

Corre en cada push a `main` y en cada PR (los de Dependabot). Mientras no haya v1 se trabaja directo en `main`: si el CI falla, se corrige con el siguiente push.

Tres jobs en `.github/workflows/ci.yml`:

- **backend:** Postgres 16, migraciones, `make check` y `pip-audit` sobre las dependencias.
- **secretos:** gitleaks sobre todo el historial.
- **imagen:** construye la imagen del backend y la escanea con Trivy.

Dependabot abre PRs semanales (Python, Docker y GitHub Actions). Fusiónalos solo con el CI en verde. No fusiones un cambio de versión mayor de Python en la imagen (p. ej. `3.13` → `3.15`) sin alinear antes `.python-version`, `pyproject.toml` y el CI.

## Secretos

Son archivos en `./secrets/`, ignorados por git. Nunca van en variables de entorno.

| Archivo | Uso |
|---|---|
| `db_password` | Superusuario de Postgres; solo crea los roles al iniciar |
| `db_migrador_password` | Rol dueño de las tablas (migraciones y bootstrap) |
| `db_app_password` | Rol de la API |
| `db_operador_password` | Rol del operador |
| `kek_v1` | Llave maestra de cifrado |

**Si pierdes `kek_vN` pierdes todos los datos cifrados.** Respáldala aparte y fuera de línea. Para cambiarla, sigue [Rotación de llaves](#rotación-de-llaves).

En desarrollo los archivos quedan con permisos 644 dentro de una carpeta 700, porque Docker Compose no cambia el dueño al montarlos y el contenedor debe poder leerlos. En producción se resuelve de otra forma.

## Rotación de llaves

Los datos personales se cifran con dos niveles de llaves:

- **KEK** (llave maestra, archivo `secrets/kek_vN`): nunca está en la base de datos. Solo sirve para "envolver" (cifrar) las DEK.
- **DEK** (llave de datos): una por clínica y una de la plataforma. Viven en la base, envueltas con la KEK. Cifran nombres, teléfonos, RFC, comentarios, etc.

Rotar una llave es cambiarla por una nueva sin perder datos. Todo se hace con el servicio `rotacion` de Docker Compose (corre como el rol `migrador`, **con la API encendida**; no hace falta parar nada). Imprime solo ids, versiones y conteos, nunca datos, y deja todo en la auditoría.

### Qué, cuándo y cómo

| Qué | Cuándo | Cómo |
|---|---|---|
| DEK de las clínicas | **Automático, una vez al año** (cron) y tras un incidente, después de rotar la KEK | `rotacion dek --todas` |
| KEK | **A mano, una vez al año** y **de inmediato** si se sospecha que se filtró (repositorio, respaldo, servidor, persona con acceso que se va) | [procedimiento](#rotar-la-kek-a-mano-paso-a-paso) |
| Verificación | **Automático, cada día** (cron) con alerta si falla | `rotacion estado --verificar` |
| DEK de plataforma (correos y TOTP) | Pospuesta: exige recalcular los índices de búsqueda con una ventana de mantenimiento | — |

### Comandos

Abrevia `docker compose -f infra/docker-compose.yml --profile tools run --rm` como `DC`:

```bash
DC rotacion estado                     # versiones de KEK y DEK en uso
DC rotacion estado --verificar         # además sale con código 1 si hay algo pendiente
DC rotacion kek                        # reenvuelve todas las DEK con la KEK activa
DC rotacion dek --clinica <uuid>       # rota la DEK de una clínica
DC rotacion dek --todas                # rota la DEK de todas las clínicas
DC rotacion dek --todas --lote 200     # filas por transacción (por defecto 500)
```

- **Rotar una DEK:** se crea la DEK nueva y la actual queda como "anterior". La API sigue leyendo con las dos y escribe con la nueva. El script espera 10 s (`--espera`) para que terminen las peticiones que ya tenían la DEK vieja, recifra por lotes todo lo que no esté en la versión nueva y, cuando no queda nada, **borra la DEK anterior**.
- **Si se interrumpe** (corte, error, `Ctrl+C`): no se pierde nada. Vuelve a correr el mismo comando y continúa donde se quedó. Mientras una clínica tenga una rotación a medias no empieza otra.
- **Código de salida:** `0` bien; `1` error, o `estado --verificar` con algo pendiente. Úsalo para alertas.

### Programarla (cron en el VPS)

Ejemplo de `crontab -e` del usuario que despliega (las rutas son provisionales hasta el paso 0.7; ajústalas):

```cron
# Rotación anual de las DEK: 15 de enero, 03:30. flock evita dos corridas a la vez.
30 3 15 1 * cd /opt/medi-clinic && flock -n /tmp/medi-rotacion.lock docker compose -f infra/docker-compose.yml --profile tools run --rm rotacion dek --todas >> /var/log/medi-clinic/rotacion.log 2>&1

# Verificación diaria, 07:00: si algo quedó pendiente (rotación a medias, DEK con una KEK vieja), alerta.
0 7 * * * cd /opt/medi-clinic && docker compose -f infra/docker-compose.yml --profile tools run --rm rotacion estado --verificar >> /var/log/medi-clinic/rotacion.log 2>&1 || curl -fsS -m 10 "$MEDI_ALERTA_URL" > /dev/null
```

- `MEDI_ALERTA_URL` es el aviso del monitoreo externo (por definir en el 0.7; p. ej. un "check" de un servicio de monitoreo o un webhook). Mientras no exista, revisa el log.
- Corre la rotación anual **después** del respaldo diario. Los respaldos anteriores guardan la DEK vieja envuelta, así que siguen pudiéndose restaurar con la KEK de su época.
- Equivalente con systemd: un `.service` con el mismo comando y un `.timer` con `OnCalendar=*-01-15 03:30`.
- Si la rotación anual falla, la verificación diaria lo detecta al día siguiente; vuelve a correr `rotacion dek --todas` a mano y revisa el log.

### Rotar la KEK (a mano, paso a paso)

La versión activa la fija `APP_KEK_ACTIVE_VERSION` (por defecto `1`); la API y el servicio `rotacion` la leen del archivo `infra/.env` (ignorado por git; no es un secreto, solo un número). Ejemplo de la v1 a la v2:

1. **Respaldo** de la base de datos.
2. **Crea la KEK nueva** y respáldala fuera de línea igual que la anterior:
   ```bash
   openssl rand -base64 32 | tr -d '\n' > secrets/kek_v2
   chmod 644 secrets/kek_v2    # en desarrollo; en producción, según el 0.7
   ```
3. **Móntala junto a la anterior** en `infra/docker-compose.yml`: agrega `kek_v2: {file: ../secrets/kek_v2}` en `secrets:` (al final) y `- kek_v2` en los servicios `api` y `rotacion`, **sin quitar `kek_v1`**.
4. **Actívala:** `echo "APP_KEK_ACTIVE_VERSION=2" >> infra/.env` y `make up`. Desde aquí las DEK nuevas se envuelven con la v2 y las existentes se siguen abriendo con la v1. **Todos los usuarios tienen que volver a iniciar sesión** (el CSRF y los contadores de intentos se derivan de la KEK).
5. **Reenvuelve:** `DC rotacion kek`.
6. **Verifica:** `DC rotacion estado --verificar` debe decir "Todo en orden" y salir con `0`.
7. **Retira la v1 de los contenedores:** quita `- kek_v1` de `api` y `rotacion` (y su entrada en `secrets:`), `make up`, y comprueba que todo funciona (iniciar sesión, ver un paciente).
8. **Archiva `kek_v1` fuera de línea; no la destruyas todavía.** Los respaldos hechos antes del paso 5 solo se restauran con ella. Destrúyela cuando el último de esos respaldos salga de la retención (6 meses, paso 0.7d).

Si algo falla a medias, no se pierde nada: mientras `kek_v1` siga montada, las DEK sin reenvolver se siguen abriendo; corrige y repite el paso 5. Para un incidente (KEK filtrada): rota la KEK, después `DC rotacion dek --todas`, y revisa la auditoría (`make auditoria` en local; `psql` en el contenedor `db` en el VPS).

## Configuración

Las opciones se sobrescriben con variables de entorno con prefijo `APP_` (por ejemplo `APP_ENTORNO`, `APP_DB_HOST`, `APP_SECRETS_DIR`). Los valores por defecto sirven en local; la lista completa está en `backend/app/config.py`.

## Correo en desarrollo

Se usa Resend por su API, sin dominio propio: crea una cuenta, guarda la API key en `secrets/resend_api_key` y usa el remitente de pruebas de Resend, que solo entrega al correo del dueño de la cuenta. Las pruebas automáticas usan un cliente simulado.

## Privacidad

Los datos personales nunca se guardan en claro, ni aparecen en logs, URLs o pruebas.