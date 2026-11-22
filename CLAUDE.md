# CLAUDE.md — medi-clinic

Agenda web **B2B** para clínicas y consultorios pequeños de México (empezando por dentistas), con recordatorios por WhatsApp y datos de pacientes cifrados. Nombre (`medi-clinic`) y dominio (`localhost`) provisionales; viven solo en `backend/app/config.py`.

Este archivo es la **fuente de verdad** del proyecto: producto, decisiones, estado y forma de trabajo. `docs/PROMPT_MAESTRO.md` y `docs/PROMPT_BACKEND.md` son **históricos**: se usaron cuando se trabajaba por prompts y ya no se actualizan. Lo que el propietario necesite para operar el proyecto (comandos, flujos, orden de pasos) va aquí o en el `README.md`, nunca solo en la conversación.

---

## 1. Estado actual (actualizar al cerrar cada paso)

- **Fase 0:** terminada salvo el paso **0.7 (infra real)**, pospuesto hasta tener nombre, dominio y VPS.
<<<<<<< HEAD
<<<<<<< Updated upstream
- **Fase 1:** pasos **1–4 terminados** y fusionados en `main` (PR #16; CI en verde el 2026-11-21). **Paso 5 (pacientes) implementado** en la rama `paso5` (2026-11-21): pruebas de BD en verde contra Postgres 16 local; falta CI y PR.
- **Siguiente:** Fase 1, **paso 6: agenda** (§10).
=======
- **Fase 1:** pasos **1–4 terminados** y fusionados en `main` (PR #16; CI en verde el 2026-11-21). **Paso 5 (pacientes) terminado** (rama `paso5`, CI en verde y PR fusionado el 2026-11-21).
- **Paso 6 (agenda y configuración de clínica) terminado** (rama `fase1-paso6`, CI en verde y PR fusionado el 2026-11-21). Desde aquí se trabaja directo en `main` (§2).
- **Siguiente:** Fase 1, **paso 7: auditoría transversal** (§10).
>>>>>>> Stashed changes
=======
- **Fase 1:** pasos **1–4 terminados** y fusionados en `main` (PR #16; CI en verde el 2026-11-21). **Paso 5 (pacientes) terminado** (rama `paso5`, CI en verde y PR fusionado el 2026-11-21).
- **Paso 6 (agenda y configuración de clínica) implementado** en la rama `fase1-paso6` (2026-11-21): pruebas de BD en verde contra Postgres 16 local; falta CI y PR (los hace el propietario).
- **Siguiente:** Fase 1, **paso 7: auditoría transversal** (§10).
>>>>>>> 1d0974906614c9d3e287ae381826473a6cb08361
- **Orden acordado:** backend (Fases 1–2) y frontend (Fase 3) primero, todo probado en local con Docker; después el 0.7 y la Fase 4.

**Pendientes menores:**
1. Prueba de "sin datos personales en logs" en los endpoints de auth (paso 0.5; sigue pendiente).
2. Invitaciones entregadas a mano: el token se devuelve una sola vez y quien invita manda el enlace. Pasar a correo automático en el paso 9.
3. Suspender una clínica borra sus sesiones, pero su personal todavía puede iniciar sesión (y `GET /api/auth/contextos` devuelve la lista vacía). Decidir si el login mismo debe fallar.
4. Desactivar a un médico con citas futuras da 409 (paso 6); sus vínculos con pacientes se conservan.
5. Dependabot ya agrupa `uv` y `github-actions` (un PR semanal por ecosistema) e ignora saltos de versión de Python en la imagen (PR #17). Quedan ramas viejas de Dependabot sin PR en `origin`; se pueden borrar.
6. Subir de Python 3.13 es decisión manual: exige alinear `Dockerfile`, `.python-version`, `pyproject.toml` y CI.
7. `apt-get install --only-upgrade zlib1g` en el `Dockerfile` es un parche temporal por Trivy: quitarlo cuando `python:3.13-slim` traiga la versión corregida.
8. Trámite con Meta (portafolio, verificación, número dedicado, nombre visible, plantillas): aún no iniciado, sin prisa; hace falta solo para la prueba real de la Fase 2.
9. Worker (aún no existe): purgar sesiones vencidas y llamar a `throttle.purgar_antiguos`; en la Fase 2, recordatorios, alertas y resumen diario.

---

## 2. Forma de trabajo

- **Idioma:** código, identificadores, mensajes de error, migraciones, documentación y commits en **español**. En la conversación, usa el idioma en que escriba el propietario. Respuestas concisas.
- **Antes de programar:** discute requisitos y diseño y confirma el plan en 5–10 líneas. Una vez acordado, **edita, crea y borra archivos directamente**: el propietario no revisa el diff si el diseño se discutió a fondo. Por eso el diseño se cierra **antes** de tocar código.
- **Lee el código antes de cambiarlo.** Antes de cambiar una tabla, política, permiso o función que ya existe, revisa el código y **las pruebas que la usan** (el paso 1 rompió pruebas de auditoría y bootstrap por no hacerlo). No adivines.
- **Una fase y un paso a la vez.** Al terminar: qué cambió, cómo probarlo y siguiente paso; actualiza §1.
- **Código y pruebas van juntos.** Si un cambio rompe una prueba existente, corrígela en el mismo cambio. Verifica siempre con `make format && make check` antes de dar algo por terminado. Lo que toca BD solo se valida en CI (§3): dilo explícitamente.
<<<<<<< HEAD
<<<<<<< Updated upstream
- **Git:** commits, push y PRs **solo cuando el propietario lo pida**. Cada paso en una rama nueva desde `main` actualizado: `git checkout main && git pull && git checkout -b faseN-pasoM`. CI en verde antes de fusionar (también los PRs de Dependabot). Los PRs se abren con `gh pr create` (cuando el propietario lo pida).
=======
- **Git:** **solo el propietario hace commits, push y PRs** (y las fusiones). Claude no los hace aunque el paso esté terminado: al cerrar un paso, indica que está listo para commit. `gh` **no está instalado** en el entorno; no lo uses ni lo sugieras como paso de Claude. **Antes de la v1 se trabaja directo en `main`** (sin ramas ni PRs propios, 2026-11-21): el CI corre una vez por push a `main` y en los PRs (Dependabot). Sin compuerta previa, si el CI falla se corrige con el siguiente push; antes de empujar cambios de BD conviene correr las pruebas de BD en local (§5). Los PRs de Dependabot sí necesitan CI en verde antes de fusionar. Al llegar la v1 (o con más gente) se vuelve a ramas + PR.
>>>>>>> Stashed changes
=======
- **Git:** **solo el propietario hace commits, push y PRs** (y las fusiones). Claude no los hace aunque el paso esté terminado: al cerrar un paso, indica que está listo para commit. `gh` **no está instalado** en el entorno; no lo uses ni lo sugieras como paso de Claude. Cada paso en una rama nueva desde `main` actualizado: `git checkout main && git pull && git checkout -b faseN-pasoM`. CI en verde antes de fusionar (también los PRs de Dependabot).
>>>>>>> 1d0974906614c9d3e287ae381826473a6cb08361
- Si algo choca con este documento, **avisa**; no cambies decisiones en silencio. Si una decisión cambia, actualiza este archivo.
- Nada fuera de alcance (§4) ni dependencias nuevas sin justificarlas en una línea (`uv add`).
- Todo modular con interfaces: canal de recordatorios, cliente de WhatsApp, proveedor de claves, proveedor de correo, pagos.
- Los textos legales son borradores sin revisión de abogado; márcalos así.
- El propietario no domina la terminología de seguridad: explica conceptos nuevos en pocas líneas (KEK = llave maestra fuera de la BD; DEK = llave de datos por clínica; AAD = etiqueta que ata el dato a su fila; índice ciego = huella para buscar sin descifrar; RLS = la BD filtra filas por clínica; IDOR = acceder a un registro ajeno cambiando el ID en la URL).
- Entorno del propietario: Ubuntu, repo en `~/Documents/personal/medi-clinic`, puerto 8000 libre.

### Reglas de código (aprendidas; no negociables)
- **Una migración ya fusionada nunca se edita.** Las correcciones van en una migración nueva. La siguiente es la **0007**.
- **Sin SQL armado con f-strings ni `# noqa: S608`.** Consultas de texto fijo con parámetros; los `UPDATE` parciales usan `CASE WHEN :bandera THEN :valor ELSE columna END`. No se silencian alertas de seguridad de ruff. (Las migraciones sí componen DDL con constantes propias, como `CID`.)
- **Textos de entrada con `StringConstraints(strip_whitespace=True, min_length=1, ...)`**, no solo `Field(min_length=1)`: un texto de solo espacios debe dar 422, no 500 ni un valor vacío guardado.
- mypy estricto: en pruebas, los resultados de `execute` se tipan con `cast("CursorResult[Any]", ...)` o ayudantes tipados.
- Ruff: reglas E, F, I, B, UP, S, SIM, C4, PT; `S101` y `S105` ignoradas en `tests/`. Longitud de línea 100.

### Comandos

| Comando | Qué hace |
|---|---|
| `make check` | ruff (lint + formato) + pytest + mypy estricto; lo mismo que el CI |
| `make format` | formatea y corrige con ruff |
| `make up` / `make down` | levanta (reconstruyendo) / apaga `db` + `api` |
| `make migrate` | `alembic upgrade head` con el rol `migrador` |
| `docker compose -f infra/docker-compose.yml --profile tools run --rm bootstrap` | crea el primer operador (interactivo, una vez por BD) |
| `cd backend && uv run pytest tests/ruta.py::prueba` | una sola prueba |

Flujo local completo: `down -v` (solo si se regeneran secretos o roles) → `make up` → `make migrate` → `bootstrap`. Los roles de BD se crean solo cuando el volumen `pgdata` está vacío.

---

## 3. Pruebas

- **Pruebas de BD solo en CI.** `db` está en una red interna de Docker sin puertos al host, así que en local se saltan (`APP_TEST_DB != "1"`) y en CI corren (`APP_TEST_DB=1`, `APP_DB_HOST=localhost`). En local, `make check` muestra muchas *skipped*: es normal. En CI, `tests/db`, `tests/api` y `tests/test_bootstrap.py` deben salir **passed**, no *skipped*. Cada cambio de BD se verifica en CI tras el push a `main` (o antes, en local; §5).
- Cada archivo de pruebas de BD lleva `pytestmark` con `pytest.mark.skipif(os.environ.get("APP_TEST_DB") != "1", reason="Pruebas de BD: solo en CI (APP_TEST_DB=1)")` (más `pytest.mark.asyncio` si usa `async`). **Sin `skipif`, el archivo falla en local** por falta de `secrets/db_app_password`.
- La BD del CI se comparte entre pruebas: cada prueba **limpia solo sus filas** de tablas hijas, con SQL propio y UUID aleatorios. Las clínicas se crean con el motor `operador` (única vía de alta; nadie tiene `DELETE` sobre `clinica`, así que quedan inertes). Las filas de `personal` y `aceptacion_legal` quedan.
- Sin datos reales en pruebas.
- **`tests/api/conftest.py`:** fixtures `client`, `otro_client` (segundo cliente con cookies propias, p. ej. operador + admin a la vez), `engine`, `platform`, `provider` (KEK en memoria); ayudantes `crear_usuario`, `crear_clinica`, `crear_invitacion_completa`, `crear_invitacion`, `crear_personal(engine, provider, cid, uid, rol, nombre)`, `crear_equipo(engine, platform, provider, *roles)` → `(cid, [Miembro(uid, pid, email)])`, `como(c, engine, platform, cid, miembro)` → abre sesión de ese miembro en el cliente `c` y devuelve `{"X-CSRF-Token": ...}`. Se importan con `from .conftest import ...`.
- `tests/test_rbac.py` compara la matriz contra una tabla **escrita aparte** (no leída de `MATRIZ`, para que no sea circular). Al añadir una `Accion`, añade su fila ahí (si no, `test_todas_las_acciones_cubiertas` falla).
- `tests/api/test_authz.py` monta un endpoint de prueba `/_t/*` solo en las pruebas.
- Pruebas obligatorias en cada recurso de clínica: IDOR entre clínicas (404), visibilidad por rol (incluido alcance `propios`), y que la BD guarde solo texto cifrado en los campos 🔒.

---

## 4. Producto

Agenda por médico (y sala, opcional) con roles. Recordatorios por **WhatsApp con la API oficial de Meta** (si la clínica lo tiene activado), desde un número único de la plataforma y solo a pacientes con autorización aceptada; confirmar y cancelar con botones dentro del chat, que actualizan la cita. Alternativa manual: lista con enlaces `wa.me` desde el WhatsApp de la clínica. Resumen diario y alertas por correo sin datos de pacientes. Alta **manual** de clínicas por el operador. La seguridad de los datos de pacientes es la prioridad. **Sin historial médico ni documentos.** Piloto: 2 consultorios gratis.

| Término | Significado |
|---|---|
| Clínica | Tenant (puede ser un solo médico: persona física). |
| Sala | Cuarto de consulta, opcional. |
| Usuario | Identidad de login global (correo, contraseña, TOTP). |
| **Personal** | Usuario + clínica + rol (`admin`, `asistente`, `medico`) + perfil (tabla `personal`; antes se llamaba "membresía"). Un usuario puede tener varios (varias clínicas). |
| Admin / Asistente / Médico | Roles de clínica. Un admin activo por clínica; solo los médicos activos cuentan para el plan. |
| Paciente | Registro dentro de una clínica; sin login; nunca se comparte entre clínicas. |
| Evento de agenda | `consulta`, `procedimiento`, `otra` o `bloqueo`, siempre en la agenda de un médico. |
| Operador | Dueño de la plataforma (el propietario); rol global aparte. **No ve datos de pacientes** (ni por la app ni por permisos de BD). Gestiona clínicas desde su panel, sin entrar al servidor. |
| Opt-in | Autorización del paciente para recordatorios por WhatsApp (casilla de la clínica + respuesta Sí del paciente). |
| Baja | El paciente pidió no recibir más mensajes; vale para todo el número de la plataforma, en todas las clínicas. |

- **Planes:** 5, 10, 20, 50 médicos (más: `custom`, por contacto). Suscripción manual y gratuita al inicio, con plan, estado (`prueba|activa|suspendida`) y vigencia desde el día 1.
- **Datos legales de la clínica:** nombre comercial, tipo de persona (`fisica|moral`), nombre legal, RFC y representante (nombre y CURP; en persona física es el titular). Los captura el operador al crear la clínica. Acepta términos y aviso **solo el admin de una clínica nueva** al activar su cuenta (`aceptacion_legal`).
- **Autorización de recordatorios:** la clínica atesta por paciente con una casilla y el paciente responde Sí a un primer mensaje neutro. Los términos hacen a la clínica responsable de los datos, de la autorización y de la exactitud de los teléfonos. **Sin validación legal** (decisión del propietario).
- Quien da de alta o cambia un paciente debe **confirmar el teléfono**. Cédula no verificada. Comentarios de cita: máx. 500 caracteres, con aviso de no escribir datos de salud.
- **Stack cerrado:** backend Python 3.13 + FastAPI; frontend React + TypeScript (Vite), mismo origen que la API (Caddy enruta `/api`); VPS único con Docker Compose y Caddy; DNS en Cloudflare; correo con Resend.
- **Fuera del MVP:** pagos y cobro automático, archivos, expediente clínico, registro público, portal de pacientes, marketplace, sincronización con calendarios externos, app nativa, analítica de terceros, control automático de la calidad del número de WhatsApp. **Enlace público de confirmación/cancelación: descartado** (no hay `token_cita`). Dejar el camino listo para pagos y cobro de mensajes.

---

## 5. Código existente (`backend/`)

**Stack:** Python 3.13, uv, FastAPI, SQLAlchemy 2 **async** + psycopg 3, Alembic (SQL explícito, `target_metadata = None`), argon2-cffi, pyotp, cryptography, pydantic-settings. Pruebas: pytest + pytest-asyncio + `starlette.testclient.TestClient` (paquete `httpx2` en dev).

- `app/config.py`: Settings (prefijo `APP_`), `read_secret`, `database_url(rol)`, `app_name`, `dominio`, `legal_version`, `invitacion_horas` (72). `app/security.py` (cabeceras). `app/main.py` (`create_app`; routers: activación, agenda, auth, clinica, operator, pacientes, personal, salas; `/docs` solo con `APP_ENTORNO=local`).
- `app/crypto/`: `keys.py` (`KeyProvider`, `FileKeyProvider`), `envelope.py` (`generate_dek`, `wrap_dek(provider, dek, contexto)`, `unwrap_dek`, `rewrap_dek`), `fields.py` (`FieldCipher`, `FieldContext(tabla, columna, clinica_id, fila_id)`), `blind_index.py` (`blind_index`, `normalize_email`), `errors.py`.
- `app/db/session.py`: `make_engine(rol)`, `clinic_session(engine, clinica_id)`.
- `app/auth/`: `passwords`, `totp`, `totp_replay` (`consumir_paso`), `recovery`, `tokens` (`new_token`, `hash_token`), `throttle`, `audit` (`registrar`; rechaza claves de metadata con pinta de dato personal; sin `clinica_id` toma el de `app.clinica_id`), `sessions` (`SessionData` con `clinica_id` y `personal_id`; `crear`, `buscar`, `asignar_contexto`, `borrar`), `platform` (`PlatformCrypto`: `cipher`, `ctx`, `email_idx`, `throttle_key`, `csrf_key`; `load_platform_crypto`), `membership` (`fijar_contexto`, `cargar_cipher`, `crear_personal`, `registrar_aceptacion`), `rbac` (`Rol`, `Alcance`, `Accion`, `MATRIZ`, `alcance(rol, accion)`).
- `app/horario.py`: `validar_zona`/`ZonaHoraria`, modelo `Horario` (tramos por día, `24:00` como fin, sin traslapes; todos vacíos = sin restricción) con `dentro(inicio, fin, zona)`, `cargar_horario`, `a_utc` (fecha sin zona = hora de la clínica).
- `app/telefono.py`: `normalizar_e164` (México `+52` por defecto; acepta `52…`, `521…` y otros `+código…`); `PlatformCrypto.telefono_idx` normaliza y usa la clave de plataforma.
- `app/api/`: `deps.py` (`SessionDep` sin commit automático, `PlatformDep`, `get_key_provider`, `client_ip`, `sesion_actual`, `sesion_completa`, `verificar_csrf`), `authz.py` (`Actor`, `requerir(accion)`), `auth.py` (login, TOTP, recuperación, logout, `/me`, `/contextos`, `/contexto`), `activation.py` (`/iniciar`, `/confirmar`, `/aceptar`), `operator.py` (panel del operador; **el módulo se llama `operator`, la ruta `/api/operador`**), `personal.py` (referencia de patrón para recursos de clínica), `salas.py`, `pacientes.py`, `clinica.py` (configuración), `agenda.py`.
- `app/scripts/bootstrap_platform.py`: DEK de plataforma + primer operador (corre con `migrador`).
- **Migraciones:** 0001 base; 0002 auth; 0003 `totp_ultimo_paso`; 0004 modelo de clínica, RLS, función `clinicas_de_usuario` (elimina `_rls_demo`); 0005 política de inserción en `auditoria` para `migrador`; 0006 el operador puede `DELETE` en `sesion` y `SELECT (clinica_id)`. **Siguiente: 0007.**
- **Infra:** `infra/docker-compose.yml` (`db`, `api`; `migrate` y `bootstrap` con perfil `tools`), `infra/db/` (`init-roles.sh`, `roles.sql`), `infra/scripts/gen-local-secrets.sh`. Dockerfile de una etapa sobre `python:3.13-slim`: parche de `zlib1g`, sin `pip`, usuario `app` 10001, sistema de archivos de solo lectura. `frontend/` vacío.
- **Pruebas de BD en local (opcional):** contenedor temporal `postgres:16` publicado en `127.0.0.1:55432`, `infra/db/init-roles.sh` (con `PGHOST/PGPORT/PGPASSWORD/POSTGRES_USER/POSTGRES_DB/SECRETS_DIR/ROLES_SQL`), `alembic upgrade head` y `pytest` con `APP_TEST_DB=1 APP_DB_HOST=127.0.0.1 APP_DB_PORT=55432 APP_SECRETS_DIR=../secrets`. No sustituye al CI.
- **CI** (`.github/workflows/ci.yml`; `dependabot.yml` vive en `.github/`, no en `workflows/`): job `backend` (Postgres 16, roles, migraciones, `make check`, `pip-audit` de producción), `secretos` (gitleaks por `docker run`, historial completo), `imagen` (build + Trivy por `docker run aquasec/trivy`, `--severity HIGH,CRITICAL --ignore-unfixed --exit-code 1`; **no se usa `trivy-action`**). Si Trivy falla por la imagen base con parche disponible, se actualiza ese paquete en el Dockerfile. En la Fase 3 se añaden `eslint`, `tsc` y `npm audit`.

### Patrón de un endpoint de clínica
1. `actor: Annotated[Actor, Depends(requerir(Accion.X))]`. Exige sesión completa (con TOTP) y **CSRF en métodos que modifican**; fija `app.clinica_id`; **lee el rol de `personal` en cada petición** (desactivar o cambiar a alguien surte efecto al instante).
2. Respuestas: **401** sin sesión o con sesión intermedia; **404 uniforme** sin contexto de clínica (operador o sin elegir), personal inexistente, ajeno o inactivo, clínica suspendida o recurso de otra clínica; **403** si el rol no tiene permiso para la acción.
3. Toda consulta filtra por `clinica_id` aunque RLS lo haga (segunda barrera). Con alcance `PROPIOS`, filtra además por `actor.personal_id` (el endpoint lo aplica).
4. Cifrar/descifrar con `membership.cargar_cipher` (requiere el contexto fijado).
5. `audit.registrar` en toda mutación, sin datos personales en la metadata.
6. **Commit explícito, también en lecturas** (persiste `ultimo_uso` de la sesión). **Tras un commit se pierde el contexto RLS:** si se vuelve a consultar, llamar otra vez a `membership.fijar_contexto`.

---

## 6. Roles y permisos

| Acción | Operador | Admin | Asistente | Médico |
|---|---|---|---|---|
| Crear clínica, invitar admin, plan/estado/vigencia, WhatsApp sí/no, suspender | sí | no | no | no |
| Ver pacientes y citas | **no** | todos | todos | solo los suyos |
| Crear/editar/cancelar citas | no | sí | sí | las suyas |
| Bloquear agenda | no | cualquier médico | cualquier médico | la suya |
| Agregar pacientes (confirmando el teléfono) | no | sí | sí | sí |
| Editar pacientes (nombre, teléfono confirmándolo, no enviar) | no | sí | sí | sus pacientes |
| Marcar la autorización de recordatorios | no | sí | sí | sus pacientes |
| Reactivar recordatorios tras baja o rechazo | no | sí | sí | sus pacientes |
| Vincular pacientes a otros médicos | no | sí | sí | no |
| Agregar médicos | no | sí | sí | no |
| Agregar asistentes | no | sí | no | no |
| Ver personal | no | todos | todos | solo a sí mismo |
| Editar personal (nombre, contacto) | no | cualquiera | solo lo suyo | solo lo suyo |
| Ver salas y la configuración de la clínica | no | sí | sí | sí |
| Crear/editar salas | no | sí | no | no |
| Configurar clínica (texto manual, política, mapa, horario) | no | sí | no | no |
| Borrar y restaurar pacientes; desactivar/reactivar personal (las citas **nunca se borran**, solo se cancelan) | no | sí | no | no |

La matriz vive **como datos** en `app/auth/rbac.py` (`MATRIZ[accion][rol] → Alcance`, `todos|propios`; rol ausente = sin permiso; el operador no figura). Acciones nuevas se agregan ahí, nunca con `if rol == ...`. Un médico solo ve pacientes vinculados a él (`paciente_medico`).

**El personal se agrega por invitación:** admin o asistente invita, cada persona fija su contraseña y TOTP (quien invita nunca conoce credenciales ajenas); reutiliza `invitacion` y los endpoints de activación.

---

## 7. Base de datos

### Roles y RLS
- **`migrador`:** dueño de las tablas, **sin `BYPASSRLS`**; migraciones y bootstrap. La API nunca recibe su secreto.
- **`app`:** conexión del backend para el personal; CRUD sin ser dueño (para que RLS aplique). Por defecto recibe CRUD de lo que crea `migrador`; las migraciones recortan con `REVOKE`.
- **`operador`:** sin permisos por defecto; los recibe por tabla en migraciones. Tiene `SELECT, INSERT, UPDATE` en `clinica`, `usuario` e `invitacion`; `SELECT` en `llave_plataforma`; `INSERT` en `auditoria`; `DELETE` y `SELECT (clinica_id)` en `sesion`. **Nunca** ve tokens ni `usuario_id` de sesión, y **ningún permiso** sobre personal, pacientes, citas ni salas (hay prueba).
- **`FORCE ROW LEVEL SECURITY` también afecta al dueño:** todo rol que lea o escriba una tabla con RLS necesita política propia. `migrador` tiene inserción en `auditoria` y lectura en `clinica` y `personal`; `operador` tiene política total en `clinica` e inserción en `auditoria`.
- Toda tabla de clínica: `clinica_id uuid NOT NULL DEFAULT nullif(current_setting('app.clinica_id', true), '')::uuid` con FK a `clinica`, y política `aislamiento_clinica` para `app` (USING y WITH CHECK).
- `app` no crea ni borra clínicas; lee la suya y actualiza solo `nombre, zona_horaria, google_maps_url, politica_cancelacion, plantilla_recordatorio, horario_laboral`. Puede hacer `SELECT … FOR UPDATE` sobre su fila de `clinica` (tope del plan). Plan, estado, vigencia y `notificaciones_whatsapp` los cambia solo el operador.
- `aceptacion_legal`: `app` solo inserta y lee. `auditoria`: `app` solo inserta (eventos sin clínica o de la suya) y lee los de su clínica. `llave_plataforma`: solo lectura para `app`.
- **`invitacion` NO tiene RLS** (la activación busca por token). **Toda consulta de `invitacion` en endpoints de clínica lleva `WHERE clinica_id = :c` escrito a mano**, con su prueba IDOR.
- **Integridad entre clínicas:** `UNIQUE (clinica_id, id)` y FK compuestas `(clinica_id, x_id)` hacia `personal`, `paciente` y `sala`. Que `paciente_medico.personal_id` y `evento_agenda.medico_id` sean médicos **lo valida la aplicación**, no la BD.
- `clinicas_de_usuario(usuario_id)`: `SECURITY DEFINER`, `search_path` fijo, ejecutable solo por `app`; devuelve `clinica_id, personal_id, rol, clinica_nombre` del personal activo en clínicas no suspendidas. Se llama solo con el id de la sesión ya autenticada.
- Todo cambio de BD es una migración Alembic en SQL explícito, con permisos por rol y RLS (y políticas para cada rol que toque la tabla).

### Tablas (UUID; 🔒 = cifrado `bytea`)
- **Auth:** `usuario` (email 🔒, email_idx, password_hash, totp_secret 🔒, totp_activo, es_operador, activo, ultimo_login, totp_ultimo_paso), `codigo_recuperacion`, `sesion` (token solo como hash; `clinica_id`, `personal_id`), `invitacion` (email 🔒, email_idx, clinica_id con FK, rol, token_hash, expira_en, usada_en, creada_por; sin RLS), `intento_login`, `llave_plataforma`, `auditoria` (clinica_id con default de contexto, actor_usuario_id, accion, entidad, entidad_id, ip, metadata; con RLS).
- **clinica:** nombre, tipo_persona, nombre_legal, rfc 🔒, representante_nombre 🔒, representante_curp 🔒, zona_horaria (IANA, por defecto `America/Mexico_City`), plan (`p5|p10|p20|p50|custom`), estado, vigencia_hasta (date), **notificaciones_whatsapp** (default false), google_maps_url, politica_cancelacion, plantilla_recordatorio (texto del canal manual `wa.me`), horario_laboral (jsonb), dek_wrapped, dek_version, creado_en.
- **personal:** usuario_id, rol, nombre 🔒, contacto_preferido 🔒 (opcional, médicos), activo, creado_en. Único (clínica, usuario); índice único parcial: un admin activo por clínica.
- **sala:** nombre, activa (se desactivan, no se borran).
- **paciente:** nombre 🔒, telefono 🔒 (E.164), telefono_idx (clave de **plataforma**, **sin unicidad**: varios familiares pueden compartir teléfono; la API solo avisa), telefono_confirmado_por y _en (obligatorios), no_enviar_recordatorios, optin_estado (`sin_solicitar|pendiente|aceptado|rechazado`), optin_atestado_por, optin_atestado_en, optin_solicitado_en, optin_respondido_en, optin_plantilla_version, creado_por, eliminado_en (borrado lógico). Check: `optin_estado ≠ sin_solicitar` exige `optin_atestado_en`. **Cambiar el teléfono exige confirmarlo de nuevo y reinicia el opt-in a `sin_solicitar`** (lo aplica la aplicación). La baja no vive aquí.
- **paciente_medico:** (paciente_id, personal_id) PK; define qué ve cada médico.
- **evento_agenda:** tipo (`consulta|procedimiento|otra|bloqueo`), medico_id (obligatorio), sala_id (nulo), paciente_id, rango (`tstzrange`), estado (`pendiente_envio|enviado|confirmada|cancelada`), comentario 🔒 (≤500, lo valida la app), cancelada_por (`paciente|personal`), enviado_en, confirmado_en, creado_por, actualizado_por (cualquier rol), creado_en, actualizado_en. Checks: `consulta` y `procedimiento` **exigen paciente**; `otra` y `bloqueo` **nunca lo llevan** y su estado es solo `confirmada` o `cancelada` (no entran al flujo de recordatorio); `cancelada_por` presente si y solo si `cancelada`; duración ≥ 15 min. Exclusiones `btree_gist` sobre `(medico_id, rango)` y `(sala_id, rango)` con estado ≠ cancelada (los bloqueos también ocupan al médico). Historial de cambios en `auditoria`. UI: se puede apartar el espacio y un pop-up pide elegir o crear al paciente; el evento no se guarda hasta asignarlo.
- **notificacion:** destinatario_id, tipo (`sin_confirmar|envio_fallido|cancelada_por_paciente|baja`), evento_id, creada_en, leida_en. Sin datos personales.
- **aceptacion_legal:** clinica_id, usuario_id, documento (`terminos|aviso`), version (`legal_version`), aceptado_en, ip.

### Falta (migración 0007, inicio de la Fase 2)
- **baja_whatsapp** (global, **sin `clinica_id` ni RLS por clínica**, solo hash): telefono_idx (clave de plataforma), creada_en, reactivada_en, reactivada_por (personal). Índice único parcial sobre `telefono_idx` donde `reactivada_en` es nulo. Se consulta antes de cada envío; el estado de baja se calcula al leer.
- **mensaje_whatsapp** (con `clinica_id` y RLS): paciente_id, evento_id (nulo en opt-in), tipo (`optin|recordatorio`), plantilla_version, wa_message_id (único), estado (`enviado|entregado|leido|fallido`), categoria (la reporta Meta), error_codigo (sin datos personales), creado_en, actualizado_en. Único por (evento_id, tipo) en recordatorios. Mide consumo por clínica y mes.
- **webhook_evento** (sin RLS): clave_unica, recibido_en. **Sin cuerpo ni teléfonos.** Idempotencia del webhook.
- Funciones de BD acotadas (estilo `clinicas_de_usuario`) para que el webhook, sin contexto de clínica, ubique paciente y cita por índice ciego y por `accion:evento_id`.

---

## 8. Seguridad (no negociable)

- **Nunca** guardes, registres en logs, pongas en URLs ni muestres datos personales en claro (nombres, teléfonos, correos, RFC, CURP). Logs sin cuerpos de petición. Sin datos reales en pruebas.
- **Cifrado:** KEK fuera de la BD, de respaldos y del repo (perderla = perder los datos) → DEK por clínica y de plataforma → índice ciego. AES-256-GCM; formato `formato(1)|versión_dek(4)|nonce(12)|cifrado+tag`; AAD `tabla|columna|clinica_id|fila_id` (`plataforma` si no hay clínica). DEK envuelta con contexto `clinica|<uuid>|v<n>` o `plataforma|v<n>`. Índice ciego: HMAC-SHA256 con clave HKDF de la DEK y la columna.
  - `usuario` usa la DEK de plataforma (`ctx("email", id)`, `ctx("totp_secret", id)`; `tabla="invitacion"` en invitaciones). Datos de clínica, su DEK: `FieldContext("clinica", columna, cid, cid)` para `rfc` y representante; `FieldContext("personal", columna, clinica_id, personal_id)` para `personal`.
  - **`paciente.telefono_idx` y el índice de `baja_whatsapp` usan la clave de plataforma** (deben coincidir entre clínicas: duplicados, webhook, baja), sobre el teléfono **normalizado a E.164**.
  - Búsqueda por nombre: descifrar en memoria la lista visible y filtrar; **sin `LIKE` sobre campos cifrados**.
  - Límite honesto: si comprometen el servidor en ejecución, pueden descifrar.
- **Autenticación:** argon2id (12–128 caracteres); TOTP de 6 dígitos, 30 s, ±1 paso, sin reutilizar; **obligatorio para admin y operador**, opcional para los demás. 10 códigos de recuperación de un solo uso (solo hash). Invitaciones de un solo uso, 72 h.
- **Login:** credenciales malas → 401 uniforme (con `verify_dummy` si la cuenta no existe); límite superado → 429 genérico. Nueva sesión al subir de nivel. **Tras el TOTP no se elige clínica automáticamente**, ni con una sola: el frontend llama a `GET /api/auth/contextos` y `POST /api/auth/contexto` (`personal_id`; 404 si no es suyo). `/me` devuelve `clinica_id` y `personal_id`.
- **Límite de intentos** (en BD, solo fallos, clave = HMAC con HKDF de la KEK): cuenta 5/5 min; IP 20/20 min; activación por IP 10/15 min y por invitación 5/15 min. Un login exitoso limpia los fallos de la cuenta, no los de la IP. Sin IP determinable, solo por cuenta. Los fallos se commitean antes de responder. IP real con `APP_IP_HEADER` (producción: `CF-Connecting-IP`).
- **Sesiones:** 8 h de inactividad, 24 h absolutas; sesión intermedia (`mfa_ok=false`) de 10 min. Cookie `HttpOnly; Secure; SameSite=Lax`, prefijo `__Host-` fuera de local. **CSRF:** HMAC del token de sesión (clave HKDF de la KEK, nada se guarda), cookie legible por JS + cabecera `X-CSRF-Token`; login y activación (`/iniciar`, `/confirmar`) exentos. El webhook de WhatsApp no usa sesión ni CSRF: se autentica con la firma de Meta.
- **Activación de invitaciones** (solo invitaciones con `clinica_id`):
  - Usuario nuevo: `POST /api/auth/activar/iniciar` (valida invitación, fija contraseña, crea usuario inactivo, devuelve secreto TOTP; reintentable) → `/confirmar` (`token`, `codigo`, `nombre`, `acepta_terminos`; verifica TOTP, consume la invitación, activa, crea `personal`, registra `aceptacion_legal` si es admin (sin aceptar → 422), crea sesión con contexto y devuelve los 10 códigos una sola vez).
  - Usuario existente: `/iniciar` da el 400 genérico; la persona inicia sesión y usa `POST /api/auth/activar/aceptar` (sesión completa + CSRF; `token`, `nombre`, `acepta_terminos`). Valida que el correo sea el suyo y que no pertenezca ya a esa clínica.
  - El `nombre` lo escribe cada persona al activar; no va en la invitación.
- **Operador:** `/api/operador/*` con el motor `operador`, sesión completa de un `es_operador` (cualquier otro: 404 uniforme), CSRF en mutaciones, todo auditado.
  - `POST /clinicas`: valida zona horaria, genera la DEK, cifra datos legales, crea clínica e **invitación del admin**; devuelve el token **una sola vez**.
  - `GET /clinicas`; `PATCH /clinicas/{id}` (plan, estado, vigencia, `notificaciones_whatsapp`; suspender borra las sesiones de la clínica al instante; los datos se conservan).
  - `GET /clinicas/{id}/invitaciones`; `POST /invitaciones/{id}/revocar` (vence ya) y `/extender` (`horas`).
  - La pantalla será frontend; se sugiere un subdominio aparte tras Cloudflare Access.
- **Personal y salas (paso 4):**
  - `PLAN_LIMITE = {p5: 5, p10: 10, p20: 20, p50: 50, custom: sin tope}` (en `personal.py`). El cupo cuenta **médicos activos + invitaciones de médico pendientes** (no vencidas ni usadas), con `SELECT … FOR UPDATE` sobre `clinica`. Al tope: 409. Invitar devuelve `medicos_usados`, `limite` y `aviso` (≥ 80 %).
  - `GET /api/personal` (admin y asistente: todos; médico: a sí mismo); `PATCH /{id}` (cada quien lo suyo; a otros solo admin; `contacto_preferido` solo médicos); `POST /{id}/desactivar` y `/reactivar` (solo admin; ni a un admin ni a uno mismo; desactivar borra sus sesiones; reactivar a un médico revalida el tope).
  - `POST /api/personal/invitaciones` (rol `asistente` o `medico`; `admin` → 422; asistentes solo los invita el admin; 409 si el correo ya es personal de esa clínica, aunque inactivo, o tiene invitación pendiente; token una sola vez), `GET /invitaciones` (admin y asistente), `POST /invitaciones/{id}/revocar`.
  - `GET /api/salas` (todos), `POST` y `PATCH /api/salas/{id}` (solo admin).
- **Pacientes (paso 5):**
  - `POST /api/pacientes` (`nombre`, `telefono`, `telefono_confirmado: true` obligatorio, `medicos`): admin y asistente vinculan ≥ 1 médico activo; el médico queda vinculado a sí mismo (vincular a otros: 403). Devuelve `telefono_repetido` (aviso, no bloqueo; misma clínica, sin eliminados).
  - `GET /api/pacientes` (`?eliminados=true` solo admin), `GET /{id}` (el admin también ve eliminados), `POST /buscar` (`{q}` en el cuerpo para no poner nombres en la URL; sin acentos ni mayúsculas, en memoria).
  - `PATCH /{id}` (`EDITAR_PACIENTE`): cambiar el teléfono exige `telefono_confirmado: true` y, si el número normalizado cambia, reinicia el opt-in.
  - `POST /{id}/autorizacion {autorizado}` (`MARCAR_OPTIN`; desmarcar → `sin_solicitar`), `POST /{id}/reactivar-recordatorios` (solo desde `rechazado`; 409 si no; gancho de `baja_whatsapp` para la Fase 2), `PUT /{id}/medicos` (reemplaza la lista; ≥ 1 médico activo), `DELETE /{id}` y `POST /{id}/restaurar` (admin).
  - Médico: paciente no vinculado = 404 en lectura y mutaciones. Auditoría: `paciente_creado|editado|autorizacion|vinculado|eliminado|restaurado`, `recordatorios_reactivados`.
- **Configuración de clínica (paso 6):** `GET /api/clinica` (todo el personal; `VER_CLINICA`), `PATCH /api/clinica` (admin; `CONFIGURAR_CLINICA`): `nombre`, `zona_horaria` (IANA), `google_maps_url` (solo `https://`), `politica_cancelacion` (≤ 500), `plantilla_recordatorio` (≤ 1000), `horario_laboral` (`{"lun": [["09:00","14:00"], ...], ..., "dom": []}`). `null` o `""` borra los textos opcionales.
- **Agenda (paso 6):**
  - `GET /api/agenda?desde&hasta` (≤ 62 días; filtros `medico_id`, `sala_id`, `paciente_id`, `incluir_canceladas`); el médico solo ve su agenda. Fechas sin zona = hora de la clínica; se guardan y devuelven en UTC.
  - `POST /api/agenda`: bloqueos con `BLOQUEAR_AGENDA`, lo demás con `GESTIONAR_CITAS` (médico: solo su agenda y sus pacientes). Valida médico activo, sala activa, paciente activo y visible, 15 min a 12 h (bloqueo hasta 31 días), comentario ≤ 500 (cifrado). Doble reserva → **409** (exclusiones de la BD). Estado inicial: `pendiente_envio` (consulta/procedimiento) o `confirmada`. Citas en el pasado permitidas.
  - Con horario laboral configurado, consulta/procedimiento/otra fuera de horario → 422 salvo `fuera_de_horario: true` (auditado). Los bloqueos no se restringen.
  - Agendar o mover a un paciente no vinculado al médico lo **vincula automáticamente** (auditado como `vinculo_automatico`).
  - `PATCH /{id}`: mover (horario, médico, sala), **cambiar de paciente** o editar el comentario; el tipo no cambia. Si cambia horario, médico o paciente de una cita `enviado`/`confirmada`, vuelve a `pendiente_envio` (`reprogramado`). Evento cancelado → 409. Guarda `actualizado_por/en`.
  - `POST /{id}/cancelar` (`cancelada_por = personal`; ya cancelado → 409). No hay `DELETE`.
  - `GET /{id}/historial`: para la UI; desde `auditoria` (quién, cuándo, campos, paciente anterior/nuevo con nombre descifrado al leer, `fuera_de_horario`, `reprogramado`). La metadata solo guarda ids.
  - Desactivar a un médico con citas futuras no canceladas (sin contar bloqueos) → 409; borrar un paciente con citas futuras → 409.
- **Cabeceras:** CSP estricta, HSTS, `X-Content-Type-Options`, `Referrer-Policy`, `frame-ancestors 'none'`. Frontend sin scripts de terceros, sin analítica, sin datos personales en `localStorage`/`sessionStorage`/URLs.
- **Secretos como archivos** en `./secrets/` (carpeta 700; archivos 644 solo en desarrollo local, porque el uid 10001 del contenedor debe leerlos; ignorados por git). Nunca en variables de entorno; sin `.env.example`. Existen: `db_password`, `db_migrador_password`, `db_app_password`, `db_operador_password`, `kek_v1`, `resend_api_key`. Fase 2: `meta_access_token`, `meta_app_secret`, `meta_verify_token`.
- **Rotación de KEK:** invalida las claves derivadas (contadores y CSRF); los usuarios vuelven a entrar. Va al runbook.
- **Hora:** UTC (`timestamptz`), mostrada en la zona de la clínica.

---

## 9. WhatsApp, recordatorios y correo (Fase 2)

**Dos modos por clínica (`clinica.notificaciones_whatsapp`, lo cambia solo el operador):**
- `false` (por defecto): sin API, sin opt-in. El personal recibe un correo con **solo el conteo y un enlace al panel**; en el panel está la lista del día con botones `wa.me` y el estado se actualiza a mano.
- `true`: recordatorios automáticos por API con opt-in; la lista manual queda para pacientes sin opt-in aceptado.

**Arquitectura:** un solo número de la plataforma (sin Embedded Signup); la plataforma paga a Meta. `MetaCloudApiChannel` detrás de `ReminderChannel`; `WaMeLinkChannel` para lo manual. Cliente HTTP detrás de `WhatsAppClient`: simulado en pruebas, número de prueba de Meta en desarrollo. El webhook real necesita HTTPS público (túnel temporal o 0.7).

**Opt-in:**
1. Alta del paciente: la API exige `telefono_confirmado = true` (en la UI, número en grande y leerlo de vuelta al paciente).
2. Casilla de la clínica ("El paciente autorizó recibir recordatorios por WhatsApp") → `optin_atestado_por/en` + auditoría. **Sin casilla no se envía nada por API.**
3. Primer mensaje `optin_v1` (un solo intento), neutro, **sin nombre ni fecha**, botones Sí / No → `pendiente`.
4. Sí → `aceptado`; No → `rechazado`. Sin respuesta queda `pendiente`: sin recordatorios y sin insistir. Dentro de la ventana de 24 h se puede enviar un acuse breve.
5. Baja ("Dejar de recibir" en cualquier mensaje) → fila en `baja_whatsapp`; bloquea ese teléfono en **todas** las clínicas. El sistema nunca la revierte solo.
6. Reactivación: solo si el paciente lo pide en la clínica; personal autorizado marca `reactivada_en` (auditado), vuelve a marcar la casilla y se repite el paso 3.

**Plantillas** (aprobadas por Meta, versionadas, estructura fija; las clínicas solo personalizan valores; cambiar el texto exige versión y aprobación nuevas):
- `optin_v1`: "{{APP_NAME}}: ¿aceptas recibir notificaciones de tus citas por WhatsApp de parte de {clínica} y {médico}? Puedes dejar de recibirlas cuando quieras." Botones **Sí · No**.
- `recordatorio_v1`: `{paciente}`, `{medico}`, `{clinica}`, `{fecha}`, `{hora}`, `{sala}`, `{politica_cancelacion}`, `{contacto_medico}` (opcional), `{enlace_mapa}`. Botones **Confirmar · Cancelar · Dejar de recibir**.
- Tono transaccional, sin tratamiento ni datos clínicos. Vigilar que Meta las mantenga como *utility* y revisar los límites de variables y botones.

**Webhook:** verificación con `meta_verify_token`; cada POST valida `X-Hub-Signature-256` (HMAC con `meta_app_secret`, tiempo constante); sin firma válida se rechaza. Límite de tamaño y peticiones; 200 rápido e idempotente (`webhook_evento`). Teléfonos entrantes: calcular índice ciego y descartar. Los botones llevan `accion:evento_id`; **validar que el teléfono remitente corresponde al paciente de la cita**. Ignorar texto libre y respuestas a citas pasadas o canceladas.

**Antes de cada envío por API:** clínica con `notificaciones_whatsapp` y no suspendida, `optin_estado = aceptado`, sin baja global activa, `no_enviar_recordatorios` falso y cita no cancelada. Cada mensaje incluye "Dejar de recibir".

**Envío automático (worker, idempotente):** citas `consulta`/`procedimiento` en `pendiente_envio` con paciente `aceptado` → `recordatorio_v1` el día anterior a una hora configurable (10:00 hora de la clínica); citas creadas después: inmediato si faltan más de 2 h. Aceptado por Meta → `enviado`; `fallido` → vuelve a `pendiente_envio` + notificación `envio_fallido`. Confirmar → `confirmada` (`confirmado_en`); Cancelar → `cancelada` (`cancelada_por = paciente`), libera el espacio y avisa. Citas `enviado` sin confirmar: alerta a asistentes y admin cada 4 h (configurable), en horario laboral y con tope.

**Lista manual (`wa.me`):** lista diaria en el panel, sin enlace de confirmación. Con WhatsApp activo: solo pacientes sin opt-in aceptado (excluye `rechazado`, baja global y `no_enviar_recordatorios`). Sin WhatsApp: todas las citas del día salvo `no_enviar_recordatorios` (si la baja global también aplica aquí está por decidir). Usa `plantilla_recordatorio`. `https://wa.me/52XXXXXXXXXX?text=<mensaje>`; validar el formato (`52…` frente a `521…`).

**Costos y calidad del número:** `mensaje_whatsapp` mide el consumo por clínica y mes. La calidad se revisa a mano en WhatsApp Manager; automatizarla queda para después.

**Correo (Resend):** interfaz `EmailProvider`, implementación por API HTTP. En desarrollo, remitente de pruebas `onboarding@resend.dev` (solo entrega al dueño de la cuenta; destinos `delivered@resend.dev` y `bounced@resend.dev`). Pruebas con cliente simulado. Los correos llevan **solo conteos y un enlace al panel** (prueba de snapshot). También enviará las invitaciones. Dominio propio (SPF, DKIM, DMARC) en el 0.7.

---

## 10. Plan por fases

### Fase 1: backend núcleo (en curso)
1. ✅ Modelos y migraciones (0004, 0005), RLS, función de login.
2. ✅ Operador, activación que crea `personal` y `aceptacion_legal`, invitaciones a usuarios existentes, contexto de clínica en la sesión (0006).
3. ✅ RBAC con matriz como datos y `requerir(accion)`.
4. ✅ `/api/personal` y `/api/salas` con límite de plan.
5. ✅ **Pacientes** (sin migración; acción nueva `EDITAR_PACIENTE`; `restaurar` incluido).
   1. `/api/pacientes`: crear, listar, ver, editar y borrado lógico (`eliminado_en`).
   2. Nombre y teléfono cifrados; **normalización E.164 adelantada desde la Fase 2** (México `+52`, sin dependencias nuevas si es posible); `telefono_idx` con clave de plataforma sobre el valor normalizado (añadir algo como `telefono_idx` a `PlatformCrypto`, junto a `email_idx`).
   3. Confirmación obligatoria del teléfono al crear; cambiarlo la repite y reinicia el opt-in.
   4. Aviso (no bloqueo) de teléfono repetido en la misma clínica.
   5. Casilla de autorización (marcar y desmarcar) y reactivación tras baja; lo que depende de `baja_whatsapp` queda como gancho.
   6. Vínculo paciente-médico, validando que sea **médico activo** de la clínica.
   7. Visibilidad: admin y asistente, todos; médico, solo vinculados.
   8. Búsqueda por nombre en memoria.
   9. Auditoría en cada mutación. Pruebas: IDOR, visibilidad por rol, teléfono sin confirmar, cambio de teléfono, nombre solo con espacios, BD solo con texto cifrado.
6. ✅ **Agenda** (crear, mover, cambiar paciente, cancelar; bloqueos; horario con `fuera_de_horario`; historial; prueba de concurrencia) y **configuración de clínica** (`/api/clinica`). Sin migración; acción nueva `VER_CLINICA`.
7. Auditoría en toda mutación (revisión transversal).
8. Scripts de rotación por lotes (reenvolver DEKs, recifrar).
9. Recuperación de contraseña (sin revelar si la cuenta existe) y envío automático de invitaciones, con `EmailProvider`.
- **Listo cuando:** la matriz RBAC pasa completa; una prueba IDOR entre clínicas falla como debe; una prueba de concurrencia no permite doble reserva; crear o cambiar un paciente sin confirmar el teléfono falla; la BD muestra solo texto cifrado en los campos 🔒.

### Fase 2: WhatsApp, recordatorios y correo
0. Migración 0007 (`baja_whatsapp`, `mensaje_whatsapp`, `webhook_evento`, funciones para el webhook).
1. Interfaces y canales; validar formato con número de prueba de Meta.
2. Opt-in: envío de `optin_v1`, estados y comprobaciones previas.
3. Webhook: verificación, firma, idempotencia, estados, botones (validando remitente), baja global, acuses.
4. Recordatorios automáticos, transiciones, fallos, alertas y resumen diario; notificaciones en app.
5. Lista manual `wa.me` y correo con conteo.
6. Medición de consumo por clínica y mes.
7. Pruebas: firma inválida; idempotencia; remitente distinto del paciente; baja global en todas las clínicas; reactivación solo autorizada; sin casilla no hay opt-in; sin `aceptado` no hay recordatorio; clínica sin WhatsApp no envía por API; correos y logs sin datos personales.
- **Listo cuando:** el flujo completo funciona en local con el cliente simulado (casilla → Sí → recordatorio → Confirmar actualiza la cita → sin respuesta genera alerta; una baja bloquea envíos). La prueba real espera al túnel o al 0.7.

### Fase 3: frontend
Vite + TypeScript + CSP; tipos generados desde OpenAPI; login, 2FA, términos y selector de clínica; calendario día/semana por médico y sala (revisar licencias: las vistas por recurso de FullCalendar son premium; evaluar react-big-calendar); pacientes (confirmación de teléfono, casilla, estado de opt-in, reactivación); lista `wa.me`; bandeja de notificaciones; configuración de clínica; panel del operador en ruta o subdominio aparte; accesibilidad; E2E con Playwright. CI: `eslint`, `tsc`, `npm audit`.
- **Listo cuando:** una secretaria completa un día de trabajo sin ayuda, en teléfono y computadora, en local.

### Paso 0.7: infra real (pospuesto)
0.7a endurecer VPS (usuario sin privilegios, SSH solo con llaves, firewall 80/443/22 limitado, `fail2ban`, actualizaciones automáticas); 0.7b Docker + Caddy + Cloudflare (proxy, SSL Full strict, límites en login, origen solo IPs de Cloudflare, ruta del webhook accesible para Meta); 0.7c esqueleto desplegado (`/health` + página vacía); 0.7d respaldos `pg_dump` cifrados con `age`, fuera del VPS, retención 7/4/6, restauración probada cada mes, KEK aparte; 0.7e Resend con dominio propio; 0.7f webhook de Meta en HTTPS y número real. Contenedores: `api`, `worker`, `db`, `caddy`. Observabilidad: monitoreo externo, rotación de logs sin datos personales, alerta si falla el respaldo o el worker.

### Fase 4: endurecimiento y piloto
Completar 0.7; prueba real de WhatsApp; revisión de seguridad (OWASP ASVS selectivo); simulacros de restauración y rotación; runbook de incidentes; borradores legales (términos con encargo de tratamiento y cláusulas de autorización, exactitud de teléfonos y suspensión por abuso; aviso de privacidad; texto modelo para clínicas); alta de 2 clínicas piloto midiendo inasistencias y calidad del número; retrospectiva.

---

## 11. Decisiones abiertas

| Tema | Por defecto |
|---|---|
| Login de personal de clínica suspendida | Hoy entra sin contextos; decidir si debe fallar |
| Baja global en clínicas sin WhatsApp (lista manual) | Por decidir |
| Horario del médico | Bloqueos puntuales; un bloqueo de varios días es un solo evento. El horario laboral es de la clínica (no por médico) |
| Retención de pacientes y citas | Borrado lógico y purga configurable (plazo por definir) |
| Hora de envío automático | Día anterior 10:00 hora de la clínica; tardías: inmediato si faltan > 2 h |
| Cobro de mensajes de WhatsApp | Propuesta: costo de Meta + 30 %, o paquete incluido |
| Calidad del número | Revisión manual en WhatsApp Manager |
| Datos legales de la clínica | Los captura el operador; evaluar moverlos al admin |
| Acceso al panel del operador | Subdominio aparte con Cloudflare Access |
| Subir de Python 3.13 | Seguir en 3.13 hasta decidirlo |
| Nombre y dominio | Provisional `medi-clinic` / `localhost` |
| VPS | 2 vCPU / 4 GB, Ubuntu 24.04 LTS |
| Respaldos | Cloudflare R2 o Backblaze B2 |
| Librería de calendario | Elegir tras revisar licencias |

**Decididas en el paso 6 (2026-11-21):** fechas sin zona en la zona de la clínica; horario laboral configurable por el admin y aplicado con `fuera_de_horario` como excepción auditada; se puede cambiar el paciente de una cita con historial visible en la UI; las citas nunca se borran (solo se cancelan); desactivar médico o borrar paciente con citas futuras → 409; agendar a un paciente no vinculado lo vincula; citas en el pasado permitidas.

**Decididas para el paso 5 (2026-11-20):** admin o asistente deben vincular al menos un médico al crear un paciente (si lo crea un médico, queda vinculado a sí mismo); la casilla de autorización se puede desmarcar y vuelve a `sin_solicitar`; el borrado lógico de pacientes lo hace y lo ve solo el admin; la normalización E.164 (México `+52`) se adelanta al paso 5.

**Decididas en el paso 4:** las invitaciones de médico pendientes cuentan para el tope; aviso al 80 %; desactivar personal corta sus sesiones; solo el admin desactiva, reactiva y edita a otros; el rol `admin` no se invita.
