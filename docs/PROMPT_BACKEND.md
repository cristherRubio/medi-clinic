# PROMPT BACKEND — medi-clinic (agenda B2B para clínicas con recordatorios)

> **HISTÓRICO (2026-11-20).** Ya no se mantiene. La fuente de verdad ahora es `CLAUDE.md`, en la raíz del repo.

> Autocontenido: pégalo al inicio de una sesión nueva para trabajar **solo el backend**. No cubre frontend, VPS ni textos legales (ver `docs/PROMPT_MAESTRO.md`).
> **Última actualización:** 2026-11-10 (tras el paso 4 de la Fase 1; CI en verde). Sincronizado con `PROMPT_MAESTRO.md` del 2026-10-29 (WhatsApp API con opt-in) más las decisiones del modelo de datos, del panel del operador, del RBAC y del personal.

---

## 0. Estado y siguiente paso

**Hecho:** cimientos (repo, Docker Compose local, cifrado de campos, BD con RLS y roles), autenticación completa (login en dos pasos, sesiones, CSRF, recuperación de códigos, activación de invitaciones, script del primer operador), CI en verde (ruff, pytest, mypy, pip-audit, gitleaks, Trivy), y **Fase 1, pasos 1 a 4**:
- Paso 1: migraciones `0004` y `0005`, RLS, función `clinicas_de_usuario`.
- Paso 2: migración `0006`, panel del operador `/api/operador/*`, activación que crea `personal` y `aceptacion_legal`, invitaciones a usuarios existentes, contexto de clínica en la sesión.
- Paso 3: RBAC con la matriz como datos (`app/auth/rbac.py`) y dependencia `requerir(accion)` (`app/api/authz.py`).
- Paso 4: `/api/personal` (listar, invitar, editar, desactivar, reactivar, invitaciones) y `/api/salas`, con límite de plan. **Sin migración nueva.**

**Siguiente: Fase 1, paso 5 (pacientes).** Plan en la sección 8. Decisiones por confirmar al inicio de la sesión (valor por defecto entre paréntesis; si el propietario dice "defaults", se asumen):
- Quien crea un paciente (admin o asistente) debe indicar al menos un médico al que se vincula, para que algún médico lo vea (sí; si crea un médico, queda vinculado a sí mismo).
- Desmarcar la casilla de autorización es posible y devuelve el opt-in a `sin_solicitar` (sí).
- El borrado lógico de pacientes lo hace y lo ve solo el admin (sí).
- La normalización del teléfono a E.164 se necesita **ya en el paso 5** (el índice ciego `telefono_idx` debe calcularse sobre el valor normalizado); se adelanta desde la Fase 2, sin dependencias nuevas si es posible (México `+52`; el formato exacto de Meta, `52…` frente a `521…`, se valida en la Fase 2).

**Archivos a pedir al propietario antes de codificar el paso 5:** `backend/app/auth/platform.py` (cómo se calcula el índice ciego; hoy hay `email_idx`, falta ver si se añade `telefono_idx`), `backend/app/api/authz.py`, `backend/app/api/personal.py` (patrón de referencia), `backend/app/auth/membership.py`, `backend/app/auth/rbac.py` y `backend/tests/api/conftest.py`. El paso 5 probablemente **no necesita migración** (la tabla `paciente` ya tiene todas las columnas); si hiciera falta, será la `0007` y la de WhatsApp pasaría a `0008`.

**Pendientes menores (anotados):**
- Prueba de "sin datos personales en logs" en los endpoints de auth.
- Las invitaciones se entregan a mano: el token se devuelve una sola vez en `POST /api/operador/clinicas` (admin) y en `POST /api/personal/invitaciones` (personal), y quien invita envía el enlace. **Refactorizar pronto** (correo automático, paso 9 con `EmailProvider`).
- Suspender una clínica borra sus sesiones, pero el login del personal sigue funcionando y `GET /api/auth/contextos` devuelve lista vacía. Decidir si el login mismo debe fallar.
- Desactivar personal **no cancela sus citas ni mueve sus pacientes**: queda para el paso 6.
- Verificar que el `.github/dependabot.yml` agrupado (un PR semanal por ecosistema `uv` y `github-actions`) esté en `main`. Los PRs viejos de Dependabot se cerraron.
- El `apt-get install --only-upgrade zlib1g` del Dockerfile es un parche temporal por Trivy; se puede quitar cuando la imagen base `python:3.13-slim` ya traiga la versión corregida.

**Cambio de rumbo (2026-10-29):** los recordatorios se envían por la **API oficial de WhatsApp** desde un número único de la plataforma, con doble autorización del paciente (sección 7). El enlace `wa.me` queda como alternativa manual. **(2026-11-02):** el enlace público de confirmación/cancelación **ya no vuelve** (no hay `token_cita`); la clínica con `notificaciones_whatsapp = false` solo usa la lista manual `wa.me`.

---

## 1. Producto (mínimo necesario)

Aplicación web **B2B** para clínicas y consultorios pequeños de México. Agenda por médico (y sala, opcional) con roles. Recordatorios por **WhatsApp con la API oficial de Meta** (si la clínica lo tiene activado), desde un número único de la plataforma y solo a pacientes con autorización aceptada; la confirmación y la cancelación se hacen con botones dentro del chat y actualizan la cita. Alternativa manual: lista con enlaces `wa.me` desde el WhatsApp de la clínica. Alta de clínicas **manual** por el operador. Seguridad de los datos de pacientes es la prioridad. **Sin historial médico ni documentos.**

| Término | Significado |
|---|---|
| Clínica | Tenant (puede ser un solo médico: persona física). |
| Sala | Cuarto de consulta, opcional. |
| Usuario | Identidad de login global (correo, contraseña, TOTP). |
| **Personal** | Usuario + clínica + rol (`admin`, `asistente`, `medico`) + perfil. Un usuario puede tener varias (varias clínicas, sobre todo médicos). Se habla de "médicos", "asistentes" y "admin" en API e interfaz. |
| Admin / Asistente / Médico | Roles de clínica. Un admin activo por clínica; solo los médicos activos cuentan para el plan. |
| Paciente | Registro dentro de una clínica; sin login; nunca se comparte entre clínicas. |
| Cita / Bloqueo | Eventos de agenda de un médico (`consulta`, `procedimiento`, `otra`, `bloqueo`). |
| Operador | Dueño de la plataforma (el propietario); rol global aparte. **No ve datos de pacientes** (ni por aplicación ni por permisos de BD). Gestiona clínicas desde un panel propio, sin entrar al servidor. |
| Opt-in | Autorización del paciente para recibir recordatorios por WhatsApp (casilla de la clínica + respuesta Sí del paciente). |
| Baja | El paciente pidió no recibir más mensajes; vale para todo el número de la plataforma, en todas las clínicas. |

**Planes:** 5, 10, 20, 50 médicos (más, contacto); suscripción manual y gratuita al inicio, pero con plan, estado (`prueba|activa|suspendida`) y vigencia desde el día 1. **Fuera de alcance:** pagos, archivos, expediente clínico, registro público, portal de pacientes, sincronización con calendarios externos, analítica de terceros, control automático de la calidad del número de WhatsApp (se revisa a mano en WhatsApp Manager) y enlace público de confirmación/cancelación (descartado por ahora). Dejar el camino listo para pagos y cobro de mensajes. Comentarios de cita: máx. 500 caracteres, con aviso de que no se escriban datos de salud.

**Autorización de recordatorios:** la clínica es responsable (términos de uso, sin validación legal): atesta por paciente con una casilla y el paciente responde Sí a un primer mensaje neutro. Decisión del propietario; es menos sólido que una firma por escrito.

**Datos legales de la clínica (simples):** nombre comercial, tipo de persona, nombre legal (razón social o nombre completo), RFC y representante (nombre y CURP). En persona física el representante es el mismo titular. **Los captura el operador** al crear la clínica (se puede mover al admin más adelante sin cambiar el modelo). Quien acepta términos y aviso es el **admin de una clínica nueva** al activar su cuenta (queda en `aceptacion_legal`); el resto del personal y los usuarios existentes que aceptan otra invitación no aceptan nada.

---

## 2. Reglas de trabajo (para la IA)

1. Responde en español, conciso. El propietario prefiere explicaciones muy cortas y no domina terminología de seguridad: explica conceptos nuevos en pocas líneas (KEK = llave maestra fuera de la BD; DEK = llave de datos por clínica; AAD = etiqueta que ata el dato a su fila; índice ciego = huella para buscar sin descifrar; RLS = la BD filtra filas por clínica; IDOR = acceder a un registro ajeno cambiando el ID en la URL).
2. **Antes de crear o modificar código, pide el contexto que falte** y confirma el plan en 5–10 líneas.
3. **La IA no ejecuta código ni ve el repo.** Entrega **solo los archivos creados o modificados, uno por uno**, con su ruta, y los comandos (`make format && make check`, commit, push). Si necesita ver un archivo existente, lo pide. Si ruff, mypy o el CI fallan, el propietario pega el error.
4. Una fase y un paso a la vez. Al terminar: qué cambió, cómo probarlo y siguiente paso. Cada bloque se confirma con `make check` y el CI en verde.
5. **Nunca** guardes, registres en logs, pongas en URLs ni muestres datos personales en claro. Sin datos reales en pruebas.
6. Si algo choca con este documento, avisa; no cambies decisiones en silencio. Sin dependencias nuevas sin justificarlas en una línea (se añaden con `uv add`).
7. Todo modular con interfaces: canal de recordatorios, cliente de WhatsApp, proveedor de correo, proveedor de claves.
8. Pruebas junto con el código, sobre todo de autorización, aislamiento entre clínicas y cifrado. Las pruebas limpian solo sus propias filas (la BD del CI se comparte).
9. Todo lo que el propietario deba saber para operar (flujos, comandos) se documenta en el README.
10. **Antes de cambiar una tabla, política, permiso o función que ya existe, pide el código y las pruebas que la usan** (el paso 1 rompió pruebas de auditoría y bootstrap por no hacerlo). No adivines: si falta un archivo, pídelo.
11. **Una migración ya fusionada nunca se edita.** Las correcciones van en una migración nueva. Cada paso se trabaja en una **rama nueva** creada desde `main` actualizado (`git checkout main && git pull` → `git checkout -b fase1-pasoN`).
12. **Sin SQL armado con f-strings ni `# noqa: S608`.** Las consultas son texto fijo con parámetros; los `UPDATE` parciales usan `CASE WHEN :bandera THEN :valor ELSE columna END`. No se silencian alertas de seguridad de ruff.
13. **Código y pruebas se entregan juntos, antes de correr `make check`** (el propietario no quiere correr el check para descubrir fallos previsibles). Si se anticipa un fallo (por ejemplo, una prueba existente que cambia), se corrige en la misma entrega. Las pruebas se escriben solo cuando se han visto los archivos reales, para no adivinar.
14. **Validar los textos con `StringConstraints(strip_whitespace=True, min_length=1, ...)`**, no con `Field(min_length=1)` solo: un texto de solo espacios debe dar 422, no 500 ni un valor vacío guardado.

---

## 3. Stack, estructura y flujo local

**Stack:** Python 3.13, uv, FastAPI, SQLAlchemy 2 **async** + psycopg 3, Alembic (SQL explícito, `target_metadata = None`), argon2-cffi, pyotp, cryptography. Pruebas con pytest + pytest-asyncio y `starlette.testclient.TestClient` (paquete `httpx2` en dev). Ruff (reglas E, F, I, B, UP, S, SIM, C4, PT; ignora `S101` y `S105` en `tests/`), mypy estricto (en pruebas, los resultados de `execute` se tipan con `cast("CursorResult[Any]", ...)` o ayudantes tipados).

**Estructura existente (`backend/`):**
- `app/config.py` (Settings, prefijo `APP_`, `read_secret`, `database_url(rol)`, `legal_version`, `invitacion_horas`), `app/security.py` (cabeceras), `app/main.py` (`create_app`; routers: activación, auth, operator, personal, salas).
- `app/crypto/`: `keys.py` (`KeyProvider`, `FileKeyProvider`), `envelope.py` (`generate_dek`, `wrap_dek(provider, dek, contexto)`, `unwrap_dek`, `rewrap_dek`), `fields.py` (`FieldCipher`, `FieldContext(tabla, columna, clinica_id, fila_id)`), `blind_index.py` (`blind_index`, `normalize_email`), `errors.py`.
- `app/db/session.py`: `make_engine(rol)`, `clinic_session(engine, clinica_id)`.
- `app/auth/`: `passwords`, `totp`, `totp_replay` (`consumir_paso`), `recovery`, `tokens` (`new_token`, `hash_token`), `throttle`, `audit` (`registrar`, rechaza claves de metadata con pinta de dato personal; **si no se pasa `clinica_id`, toma el de la sesión (`app.clinica_id`)**), `sessions` (`SessionData` con `clinica_id` y `personal_id`; `crear`, `buscar`, `asignar_contexto`, `borrar`), `platform` (`PlatformCrypto` con `cipher`, `ctx`, `email_idx`, `throttle_key`, `csrf_key`; `load_platform_crypto`), `membership` (`fijar_contexto`, `cargar_cipher`, `crear_personal`, `registrar_aceptacion`), **`rbac`** (`Rol`, `Alcance`, `Accion`, `MATRIZ`, `alcance(rol, accion)`).
- `app/api/`: `deps.py` (`SessionDep` sin commit automático, `PlatformDep`, `get_key_provider`, `client_ip`, `sesion_actual`, `sesion_completa`, `verificar_csrf`), `auth.py` (login, TOTP, recuperación, logout, `/me`, `/contextos`, `/contexto`), `activation.py` (`/iniciar`, `/confirmar`, `/aceptar`), **`operator.py`** (panel del operador; **el módulo se llama `operator`, no `operador`**), **`authz.py`** (`Actor`, `requerir(accion)`), **`personal.py`**, **`salas.py`**.
- `app/scripts/bootstrap_platform.py`: crea la DEK de plataforma y el primer operador (corre con `migrador`).
- **Migraciones:** 0001 (base; su `_rls_demo` la elimina la 0004), 0002 (auth), 0003 (`totp_ultimo_paso`), 0004 (modelo de clínica, RLS, función de login), 0005 (política de inserción en `auditoria` para `migrador`), 0006 (el operador puede `DELETE` en `sesion` y `SELECT (clinica_id)`). **La siguiente es la 0007** (el paso 5 probablemente no la necesita; si no, la usa la Fase 2).
- **Pruebas:** `tests/auth|db|api` (+ `tests/api/conftest.py`), `tests/test_bootstrap.py`, `tests/test_config.py`. `tests/auth/test_rbac.py` (la matriz contra una tabla escrita aparte desde la sección 5, **no** leída de `MATRIZ`, para que no sea circular; no toca BD). `tests/db/test_rls.py`, `tests/db/test_modelo_clinica.py`, `tests/db/test_operador_permisos.py`. `tests/api/`: `test_auth`, `test_activation`, `test_operador`, `test_authz` (endpoint de prueba `/_t/*` montado solo en `tests/` sobre la app del cliente; ayudantes propios), `test_personal`, `test_salas`.
- **`tests/api/conftest.py`:** fixtures `client`, `otro_client` (segundo cliente con cookies propias, p. ej. operador + admin a la vez), `engine`, `platform`, `provider` (KEK en memoria); ayudantes `crear_usuario`, `crear_clinica`, `crear_invitacion_completa`, `crear_invitacion`, `crear_personal(engine, provider, cid, uid, rol, nombre)`, `crear_equipo(engine, platform, provider, *roles)` → `(cid, [Miembro(uid, pid, email)])` (nombres "Persona 0", "Persona 1"…), `como(c, engine, platform, cid, miembro)` → abre sesión de ese miembro en el cliente `c` y devuelve la cabecera `{"X-CSRF-Token": ...}`. Los archivos de prueba importan con `from .conftest import ...`.

**Convención de pruebas de BD:** cada archivo de BD lleva `pytestmark` con `pytest.mark.skipif(os.environ.get("APP_TEST_DB") != "1", reason="Pruebas de BD: solo en CI (APP_TEST_DB=1)")` (y `pytest.mark.asyncio` en los de BD si usan `async`); un archivo sin `skipif` intenta abrir la BD en local y falla por falta de `secrets/db_app_password`. Las clínicas de prueba las crea el motor `operador` (única vía de alta; nadie tiene `DELETE` sobre `clinica`, así que quedan inertes en la BD desechable del CI); cada prueba limpia solo sus filas de tablas hijas (las filas de `personal` y `aceptacion_legal` quedan); los datos se insertan con SQL propio y UUID aleatorios.

**Flujo local** (Docker Compose, archivo `infra/docker-compose.yml`; `db` está en red interna sin puertos al host):
`down -v` (solo si se regeneran secretos) → `make up` → `make migrate` → `docker compose -f infra/docker-compose.yml --profile tools run --rm bootstrap`. Los roles de BD se crean solo con el volumen vacío (`infra/` tiene `roles.sql` y su script de arranque). `migrate` y `bootstrap` son servicios del perfil `tools` y usan el rol `migrador`. Comandos `make`: `help`, `check` (ruff + pytest + mypy), `format`, `up`, `down`, `migrate`.

**Pruebas de BD solo en CI:** en local se saltan (`APP_TEST_DB != "1"`); el CI define `APP_TEST_DB=1` y `APP_DB_HOST=localhost`. Las pruebas de `tests/db`, `tests/api` y `tests/test_bootstrap.py` deben salir *passed* en CI, no *skipped*. Cada cambio de BD se verifica empujando una rama.

**Secretos como archivos** en `./secrets/` (carpeta 700; archivos 644 solo en desarrollo local; `secrets/` en `.gitignore`): `db_password`, `db_migrador_password`, `db_app_password`, `db_operador_password`, `kek_v1`; para correo, `resend_api_key`; **para WhatsApp (Fase 2):** `meta_access_token`, `meta_app_secret`, `meta_verify_token`. Nunca en variables de entorno.

**CI** (`.github/workflows/ci.yml`; `dependabot.yml` va en `.github/`, no en `workflows/`): job `backend` (Postgres 16, roles, migraciones, `make check`, `pip-audit` de producción), `secretos` (gitleaks por `docker run`) e `imagen` (construye `backend/Dockerfile` y corre Trivy con `docker run aquasec/trivy`, `--severity HIGH,CRITICAL --ignore-unfixed --exit-code 1`; **no se usa `trivy-action`**). Dockerfile de una sola etapa sobre `python:3.13-slim`: actualiza `zlib1g` con `apt-get` (parche temporal), sin `pip`, usuario `app` 10001, sistema de archivos de solo lectura. Dependabot: semanal, agrupado por ecosistema (`uv`, `github-actions`; `docker` sin agrupar). Si Trivy falla por una vulnerabilidad de la imagen base con parche disponible, se actualiza ese paquete en el Dockerfile.

---

## 4. Decisiones de implementación (prevalecen si chocan)

- **Roles de BD:** `migrador` (dueño de tablas, **sin `BYPASSRLS`**), `app` (CRUD sin ser dueño, para que RLS aplique; es la conexión del backend para admin, asistentes y médicos), `operador` (sin permisos por defecto; se otorgan por tabla en migraciones; lo usa el backend para el panel del operador). Por defecto `app` recibe CRUD de lo que crea `migrador`; las migraciones recortan casos especiales con `REVOKE`.
- **RLS forzado (`FORCE ROW LEVEL SECURITY`) afecta también al dueño.** Todo rol que escriba o lea una tabla con RLS necesita política propia. Por eso: `migrador` tiene política de inserción en `auditoria` (bootstrap) y de lectura en `clinica` y `personal` (función de login); `operador` tiene política total en `clinica` y de inserción en `auditoria`. Toda tabla de clínica lleva `clinica_id uuid NOT NULL DEFAULT nullif(current_setting('app.clinica_id', true), '')::uuid` con FK a `clinica` y política `aislamiento_clinica` para `app` (USING y WITH CHECK).
- **Permisos específicos:** `app` **no** crea ni borra clínicas; solo lee la suya y actualiza `nombre, zona_horaria, google_maps_url, politica_cancelacion, plantilla_recordatorio, horario_laboral`. Plan, estado, vigencia y `notificaciones_whatsapp` los cambia solo el operador. `operador` tiene `SELECT, INSERT, UPDATE` en `clinica`, `usuario` e `invitacion`, `SELECT` en `llave_plataforma`, `INSERT` en `auditoria` y, desde la 0006, `DELETE` y `SELECT (clinica_id)` en `sesion` (para suspender); **nunca ve tokens ni `usuario_id` de sesión, y ningún permiso sobre personal, pacientes, citas ni salas** (hay prueba). `aceptacion_legal`: `app` solo inserta y lee. `auditoria`: `app` solo inserta (eventos sin clínica o de la suya) y lee solo los de su clínica. `app` puede hacer `SELECT … FOR UPDATE` sobre su fila de `clinica` (lo usa el cálculo del tope de plan; verificado en CI).
- **`invitacion` NO tiene RLS** (la activación busca por token, sin contexto de clínica). **Toda consulta de `invitacion` en endpoints de clínica debe llevar `WHERE clinica_id = :c` escrito a mano**, con su prueba IDOR.
- **Integridad entre clínicas:** `UNIQUE (clinica_id, id)` y FK compuestas `(clinica_id, x_id)` hacia `personal`, `paciente` y `sala`, para que nada mezcle clínicas. El rol médico de `paciente_medico.personal_id` y `evento_agenda.medico_id` **lo valida la aplicación**, no la BD.
- **Autorización (pasos 3–4):** matriz como datos en `app/auth/rbac.py` (enums `Rol`, `Alcance` = `todos|propios`, `Accion`; `MATRIZ[accion][rol] → Alcance`, rol ausente = sin permiso; el operador no figura). Dependencia `requerir(accion)` (`app/api/authz.py`) se usa como `Annotated[Actor, Depends(requerir(Accion.X))]` y devuelve `Actor(usuario_id, personal_id, clinica_id, rol, alcance)`. Exige sesión completa (con TOTP) y **CSRF en métodos que modifican**; fija `app.clinica_id` en la transacción de la petición; **lee el rol de `personal` en cada petición** (no se guarda en la sesión), así desactivar o cambiar a alguien surte efecto de inmediato. Respuestas: **401** sin sesión o sesión intermedia; **404 uniforme** si no hay contexto de clínica (operador o sin elegir), si el personal no existe, no es del usuario o está inactivo, si la clínica está suspendida o si el recurso es de otra clínica; **403** si el rol no tiene permiso para la acción. Cada consulta filtra además por `clinica_id` (RLS es la segunda barrera). **Ojo:** `fijar_contexto` dura hasta el commit; si un endpoint hace commit y luego vuelve a consultar, debe llamarlo de nuevo. Los endpoints hacen commit explícito (también en lecturas, para persistir `ultimo_uso` de la sesión). IDs UUID.
- **Personal y salas (paso 4):**
  - Planes: `PLAN_LIMITE = {p5: 5, p10: 10, p20: 20, p50: 50, custom: sin tope}` (en `personal.py`). El cupo cuenta **médicos activos + invitaciones pendientes de médico** (no vencidas ni usadas), con `SELECT … FOR UPDATE` sobre `clinica` para evitar carreras. Los asistentes y el admin no cuentan. Al llegar al tope: 409. La respuesta de invitar trae `medicos_usados`, `limite` y `aviso` (verdadero al 80 % o más).
  - `GET /api/personal` (admin y asistente ven todos; el médico solo a sí mismo), `PATCH /api/personal/{id}` (cada quien edita lo suyo; editar a otros exige `EDITAR_PERSONAL`, solo admin; `contacto_preferido` solo para médicos), `POST /{id}/desactivar` y `/reactivar` (`BORRAR`, solo admin; no se desactiva a un admin ni a uno mismo; desactivar borra las sesiones de ese `personal_id`; reactivar a un médico revalida el tope).
  - `POST /api/personal/invitaciones` (rol `asistente` o `medico`; `admin` da 422, uno por clínica; invitar asistentes exige `AGREGAR_ASISTENTES`, solo admin; 409 si el correo ya es personal de esa clínica, aunque esté inactivo, o ya tiene invitación pendiente; devuelve el token **una sola vez**), `GET /invitaciones` (admin y asistente), `POST /invitaciones/{id}/revocar` (mismo permiso que invitar ese rol).
  - `GET /api/salas` (todos los roles), `POST` y `PATCH /api/salas/{id}` (solo admin; las salas se desactivan con `activa`, no se borran).
- **Login con varias clínicas:** la función `clinicas_de_usuario(usuario_id)` (`SECURITY DEFINER`, `search_path` fijo, ejecutable solo por `app`) devuelve `clinica_id, personal_id, rol, clinica_nombre` de personal activo en clínicas no suspendidas. Se invoca solo con el id de la sesión ya autenticada (sin contexto de clínica). `sesion` guarda `clinica_id` y `personal_id` (nulos para el operador y en el paso intermedio). **Endpoints:** `GET /api/auth/contextos` lista las clínicas del usuario; `POST /api/auth/contexto` (`personal_id`) fija la elegida en la sesión (404 si no es suya); `/me` devuelve `clinica_id` y `personal_id`. Tras el TOTP **no se elige clínica automáticamente**, ni siquiera con una sola: el frontend llama a esos dos endpoints. Una clínica suspendida: se borran sus sesiones, deja de aparecer en `contextos` y conserva los datos.
- **Cifrado:** valores `BYTEA` con formato `formato(1)|versión_dek(4)|nonce(12)|cifrado+tag` (AES-256-GCM); AAD `tabla|columna|clinica_id|fila_id` (`plataforma` si no hay clínica). DEK envuelta con la KEK con contexto `clinica|<uuid>|v<n>` o `plataforma|v<n>`. Índice ciego: HMAC-SHA256 con clave HKDF de la DEK y la columna. Búsqueda por nombre: descifrar en memoria la lista del médico y filtrar; **sin `LIKE` sobre campos cifrados**. Contextos de cifrado en auth: `ctx("email", id)`, `ctx("totp_secret", id)`, `tabla="invitacion"`. Los datos de `usuario` usan la DEK de plataforma; los de clínica, su DEK (`membership.cargar_cipher`, requiere el contexto de la clínica fijado). **`paciente.telefono_idx` y el índice de `baja_whatsapp` usan la clave de plataforma** (debe coincidir entre clínicas y sirve para duplicados, webhook y baja). Campos cifrados de clínica (contexto `FieldContext("clinica", columna, cid, cid)`): `rfc`, `representante_nombre`, `representante_curp`. `personal.nombre` y `personal.contacto_preferido` se cifran con `FieldContext("personal", columna, clinica_id, personal_id)`.
- **Sesiones:** tabla `sesion` (token solo como hash); 8 h de inactividad, 24 h absolutas; sesión intermedia (`mfa_ok=false`) de 10 min. Cookie `HttpOnly; Secure; SameSite=Lax`, prefijo `__Host-` fuera de local. **CSRF:** HMAC del token de sesión (clave HKDF de la KEK, nada se guarda), cookie legible por JS y cabecera `X-CSRF-Token` en operaciones con sesión; login y activación (`/iniciar`, `/confirmar`) exentos. **El webhook de WhatsApp no usa sesión ni CSRF: se autentica con la firma de Meta** (sección 6).
- **Login:** credenciales malas → 401 uniforme (con `verify_dummy` si la cuenta no existe); límite superado → 429 genérico. Admin y operador exigen TOTP (operador sin TOTP no entra); para los demás es opcional. Nueva sesión al subir de nivel; con varias clínicas, el usuario elige contexto al entrar.
- **Límite de intentos (en BD, solo fallos, clave = HMAC con HKDF de la KEK):** cuenta 5 en 5 min; IP 20 en 20 min; activación por IP 10 en 15 min y por invitación 5 en 15 min. Un login exitoso limpia los fallos de la cuenta, no los de la IP. Sin IP determinable solo se limita por cuenta. Los fallos se commitean antes de responder el error.
- **IP real:** cabecera configurable `APP_IP_HEADER` (en producción `CF-Connecting-IP`).
- **Activación de invitación:** solo hay invitaciones con `clinica_id` (las demás no se activan).
  - Usuario nuevo, en dos pasos: `/api/auth/activar/iniciar` (valida invitación, fija contraseña, crea usuario `activo=false`, devuelve secreto TOTP; reintentable) y `/confirmar` (verifica TOTP, consume la invitación, activa, **crea `personal` con su `nombre`**, registra `aceptacion_legal` si el rol es `admin`, crea la sesión con `clinica_id` y `personal_id`, devuelve 10 códigos de recuperación una sola vez). Campos de `/confirmar`: `token`, `codigo`, `nombre`, `acepta_terminos` (obligatorio si el rol es admin; si falta, 422).
  - **Usuario existente:** si el email ya tiene cuenta activa, `/iniciar` responde el 400 genérico; la persona inicia sesión y usa `POST /api/auth/activar/aceptar` (sesión completa + CSRF; `token`, `nombre`, `acepta_terminos`). Valida que el correo de la invitación sea el suyo (si no, 400 genérico), que no pertenezca ya a esa clínica, consume la invitación, crea `personal` y deja el contexto en la sesión.
  - Invitaciones de un solo uso, 72 h. **El `nombre` lo escribe cada persona al activar** (no va en la invitación). `aceptacion_legal` guarda `terminos` y `aviso` con `legal_version` (config).
- **Operador (panel sin entrar al servidor):** endpoints `/api/operador/*` con el motor `operador` (`get_operador_session`, en `app/api/operator.py`), exigiendo sesión completa (con TOTP) de un `es_operador`; para cualquier otro usuario, 404 uniforme. Mutaciones con CSRF; todo se audita.
  - `POST /clinicas`: valida zona horaria, genera la DEK de la clínica, cifra los datos legales, crea la clínica **y la invitación del admin**; devuelve el **token una sola vez** (el operador arma el enlace y lo envía a mano por ahora).
  - `GET /clinicas`; `PATCH /clinicas/{id}` (plan, estado, vigencia, `notificaciones_whatsapp`; suspender y reactivar son `estado`; al suspender borra las sesiones de la clínica en el acto).
  - `GET /clinicas/{id}/invitaciones`; `POST /invitaciones/{id}/revocar` (pone `expira_en` en el pasado) y `/extender` (`horas`).
  - La pantalla es frontend; se sugiere servirla en un subdominio aparte tras Cloudflare Access (se ve en la parte de VPS).
- **Privacidad:** logs sin cuerpos de petición ni datos personales; `audit.registrar` rechaza metadata con claves de dato personal. Docs de la API (`/docs`) solo con `APP_ENTORNO=local`.
- **Hora:** UTC (`timestamptz`), mostrada en la zona de la clínica (IANA, por defecto `America/Mexico_City`); eventos de mínimo 15 min (check en BD).
- **Pendiente para el worker:** purgar sesiones vencidas y llamar a `throttle.purgar_antiguos`; (Fase 2) enviar recordatorios, alertas de citas sin confirmar y resumen diario.
- **Rotación de KEK** invalida claves derivadas (contadores y CSRF); los usuarios vuelven a entrar. Va al runbook.
- **Correo:** interfaz `EmailProvider`; implementación Resend por API HTTP. En desarrollo, sin dominio: remitente de pruebas `onboarding@resend.dev` (solo entrega al correo del dueño de la cuenta; existen destinos de prueba como `delivered@resend.dev` y `bounced@resend.dev`, verificar en su documentación vigente), API key en `secrets/resend_api_key`. Pruebas automatizadas con cliente simulado. Los correos llevan **solo conteos y un enlace al panel**, nunca nombres ni teléfonos (prueba de snapshot). También enviará las invitaciones (hoy manuales).
- **WhatsApp (decidido 2026-10-29):** un solo número de la plataforma (sin Embedded Signup); la plataforma paga a Meta y el cobro a las clínicas se define después. Canal principal `MetaCloudApiChannel` detrás de `ReminderChannel`; `WaMeLinkChannel` como alternativa manual. Cliente HTTP detrás de la interfaz `WhatsAppClient`: **simulado en pruebas**; en desarrollo, número de prueba de Meta. El webhook real necesita HTTPS público (túnel temporal o despliegue en VPS), por eso la prueba real queda para después de la Fase 2 en local. Se activa por clínica con `clinica.notificaciones_whatsapp` (por defecto `false`, lo cambia solo el operador). Orden del opt-in y especificación completa en la sección 7.

---

## 5. Roles, permisos y modelo de datos

| Acción | Operador | Admin | Asistente | Médico |
|---|---|---|---|---|
| Crear clínica, invitar admin, plan/estado/vigencia, WhatsApp sí/no, suspender | sí | no | no | no |
| Ver pacientes y citas | **no** | todos | todos | solo los suyos |
| Crear/editar/cancelar citas | no | sí | sí | las suyas |
| Bloquear agenda | no | cualquier médico | cualquier médico | la suya |
| Agregar pacientes (confirmando el teléfono) | no | sí | sí | sí |
| Marcar la autorización de recordatorios | no | sí | sí | sus pacientes |
| Reactivar recordatorios tras baja o rechazo (a petición del paciente en la clínica) | no | sí | sí | sus pacientes |
| Vincular pacientes a otros médicos | no | sí | sí | no |
| Agregar médicos | no | sí | sí | no |
| Agregar asistentes | no | sí | no | no |
| Ver personal | no | todos | todos | solo a sí mismo |
| Editar personal (nombre, contacto) | no | cualquiera | solo lo suyo | solo lo suyo |
| Ver salas | no | sí | sí | sí |
| Crear/editar salas | no | sí | no | no |
| Configurar clínica (texto manual, política, mapa, horario) | no | sí | no | no |
| Borrar (pacientes, citas) y desactivar/reactivar personal | no | sí | no | no |

La matriz vive **como datos** en `app/auth/rbac.py` (acciones: `VER_PACIENTES`, `GESTIONAR_CITAS`, `BLOQUEAR_AGENDA`, `CREAR_PACIENTE`, `MARCAR_OPTIN`, `REACTIVAR_RECORDATORIOS`, `VINCULAR_PACIENTES`, `AGREGAR_MEDICOS`, `AGREGAR_ASISTENTES`, `GESTIONAR_SALAS`, `CONFIGURAR_CLINICA`, `BORRAR`, `VER_PERSONAL`, `EDITAR_PERSONAL`, `VER_SALAS`); las pruebas se parametrizan contra una tabla escrita aparte. Al añadir una acción hay que añadir su fila en `tests/auth/test_rbac.py` (si no, `test_todas_las_acciones_cubiertas` falla). Un médico solo ve pacientes vinculados a él (alcance `propios`; el filtro lo aplica cada endpoint, desde el paso 5). Un usuario con varias clínicas elige contexto al entrar. Un admin activo por clínica. **El personal se agrega por invitación** (el admin o asistente invita, cada persona fija su contraseña y TOTP; quien invita nunca conoce credenciales ajenas): reutiliza la tabla `invitacion` y los endpoints de activación.

### Ya existe (migraciones 0002–0006)
- Auth: `usuario` (id, email 🔒, email_idx, password_hash, totp_secret 🔒, totp_activo, es_operador, activo, ultimo_login, totp_ultimo_paso), `codigo_recuperacion`, `sesion` (+ `clinica_id`, `personal_id`), `invitacion` (email 🔒, email_idx, `clinica_id` con FK, rol, token_hash, expira_en, usada_en, creada_por; **sin RLS**), `intento_login`, `llave_plataforma`.
- `auditoria` (clinica_id con default de contexto, actor_usuario_id, accion, entidad, entidad_id, ip, metadata) con RLS.
- **clinica**: id, nombre, tipo_persona (`fisica|moral`), nombre_legal, rfc 🔒, representante_nombre 🔒, representante_curp 🔒, zona_horaria, plan (`p5|p10|p20|p50|custom`), estado (`prueba|activa|suspendida`), vigencia_hasta (date), notificaciones_whatsapp (default false), google_maps_url, politica_cancelacion, plantilla_recordatorio (texto del canal manual `wa.me`), horario_laboral (jsonb), dek_wrapped, dek_version, creado_en.
- **personal**: id, clinica_id, usuario_id, rol, nombre 🔒, contacto_preferido 🔒 (opcional, médicos), activo. Único (clínica, usuario); índice único parcial: un admin activo por clínica.
- **sala**: id, clinica_id, nombre, activa.
- **paciente**: nombre 🔒, telefono 🔒 (E.164), telefono_idx (clave de plataforma, **sin unicidad**: un teléfono puede ser de varios familiares; la API solo avisa al crear), telefono_confirmado_por y telefono_confirmado_en (obligatorios), no_enviar_recordatorios, optin_estado (`sin_solicitar|pendiente|aceptado|rechazado`), optin_atestado_por, optin_atestado_en, optin_solicitado_en, optin_respondido_en, optin_plantilla_version, creado_por, eliminado_en (borrado lógico). Check: `optin_estado` distinto de `sin_solicitar` exige `optin_atestado_en`. FK compuestas a `personal` (confirmado_por, atestado_por, creado_por). **Cambiar el teléfono exige confirmarlo de nuevo y reinicia el opt-in a `sin_solicitar`** (lo aplica la aplicación). La baja no vive aquí (ver `baja_whatsapp`).
- **paciente_medico**: paciente_id, personal_id (define la visibilidad del médico). PK (paciente, personal).
- **evento_agenda**: id, clinica_id, tipo (`consulta|procedimiento|otra|bloqueo`), medico_id (de quién es la agenda; obligatorio), sala_id (nulo), paciente_id, rango (`tstzrange`), estado (`pendiente_envio|enviado|confirmada|cancelada`), comentario 🔒 (≤500, lo valida la aplicación), cancelada_por (`paciente|personal`), enviado_en, confirmado_en, creado_por, actualizado_por (personal de **cualquier rol**), creado_en, actualizado_en. Checks: `consulta` y `procedimiento` **exigen paciente**; `otra` y `bloqueo` **nunca lo llevan** y su estado es solo `confirmada` o `cancelada` (no entran al flujo de recordatorio); `cancelada_por` presente si y solo si el estado es `cancelada`; duración ≥ 15 min. Exclusiones (`btree_gist`) sobre `(medico_id, rango)` y `(sala_id, rango)` con estado ≠ cancelada (los bloqueos también ocupan al médico). **Flujo de interfaz:** se puede apartar el espacio y un pop-up pide elegir o crear al paciente al instante; el evento no se guarda hasta asignarlo. Si el envío de un recordatorio falla, la cita vuelve a `pendiente_envio` y se notifica al personal. El historial de cambios vive en `auditoria`.
- **notificacion** (alertas internas al personal, sin datos personales): destinatario_id, tipo (`sin_confirmar|envio_fallido|cancelada_por_paciente|baja`), evento_id, creada_en, leida_en.
- **aceptacion_legal**: clinica_id, usuario_id, documento (`terminos|aviso`), version, aceptado_en, ip.

### Falta (migración 0007, inicio de la Fase 2)
- **baja_whatsapp** (global, **sin `clinica_id` ni RLS por clínica**, solo hash): id, telefono_idx (clave de **plataforma**), creada_en, reactivada_en (nulo), reactivada_por (personal, nulo). Índice único parcial sobre `telefono_idx` donde `reactivada_en` es nulo. Se consulta antes de cada envío; el estado de baja de un paciente se calcula al leer, sin tocar sus filas.
- **mensaje_whatsapp** (con `clinica_id` y RLS): id, paciente_id, evento_id (nulo en opt-in), tipo (`optin|recordatorio`), plantilla_version, wa_message_id (único), estado (`enviado|entregado|leido|fallido`), categoria (la reporta Meta), error_codigo (sin datos personales), creado_en, actualizado_en. Único por (`evento_id`, `tipo`) en recordatorios, para no duplicar envíos. Mide el consumo por clínica y mes.
- **webhook_evento** (sin RLS): clave_unica (id de mensaje o de estado entrante + tipo), recibido_en. **Sin cuerpo ni teléfonos.** Da idempotencia al webhook.
- El webhook, igual que el login, no tiene contexto de clínica: necesitará funciones de BD acotadas (estilo `clinicas_de_usuario`) para ubicar paciente y cita por teléfono (índice ciego) y botón (`accion:evento_id`). Se diseña en la 0007.

La auditoría registra quién atestó, confirmó el teléfono o reactivó, y cuándo (sin datos personales en la metadata).

---

## 6. Seguridad (no negociable)

- Cifrado de campos con KEK (fuera de la BD, de respaldos y del repo; perderla = perder los datos) → DEK por clínica y de plataforma → índice ciego. Límite honesto a documentar: si comprometen el servidor en ejecución, pueden descifrar.
- Autorización centralizada + RLS; 404 uniforme para recursos ajenos; pruebas de IDOR entre clínicas.
- Logs sin datos personales; sin datos personales en URLs.
- Cabeceras: CSP estricta, HSTS, `X-Content-Type-Options`, `Referrer-Policy`, `frame-ancestors 'none'`.
- **Webhook de WhatsApp:**
  - Verificación inicial con `meta_verify_token`; cada POST se valida con la firma `X-Hub-Signature-256` (HMAC con `meta_app_secret`, comparación en tiempo constante). Sin firma válida, se rechaza.
  - Límite de tamaño y de peticiones; responder 200 rápido y de forma idempotente (`webhook_evento`).
  - Los teléfonos que llegan en el webhook son datos personales: se calcula el índice ciego y se descartan. Nunca en logs ni almacenados en claro.
  - Una respuesta con botón lleva `accion:evento_id`. **Antes de actuar, validar que el teléfono remitente corresponde al paciente de esa cita.** Se ignora el texto libre y las respuestas a citas pasadas o canceladas.
- **Antes de cada envío por API** comprobar: clínica con `notificaciones_whatsapp` activo, `optin_estado = aceptado`, sin baja global activa, `no_enviar_recordatorios` falso, clínica activa (no suspendida) y cita no cancelada. Cada mensaje incluye la opción "Dejar de recibir".
- Todo cambio de BD pasa por migración Alembic en SQL explícito, con permisos por rol y RLS en tablas con `clinica_id` (y políticas para todo rol que las toque, ver sección 4).

---

## 7. Recordatorios (especificación)

### 7.0 Dos modos por clínica (`notificaciones_whatsapp`)
- **`false` (por defecto):** sin API de WhatsApp, sin opt-in y sin enlaces de confirmación. El personal recibe un **correo con solo el conteo y un enlace al panel**; en el panel está la lista del día con botones `wa.me` y el personal actualiza el estado a mano (sección 7.4).
- **`true` (lo activa el operador):** recordatorios automáticos por API con opt-in (7.1–7.3); la lista manual queda para pacientes sin opt-in aceptado.

### 7.1 Autorización del paciente (opt-in)
1. **Alta del paciente.** La API exige `telefono_confirmado = true` (quien da de alta revisa el número y lo confirma). Sin esa confirmación, el alta falla. Cambiar el teléfono repite la confirmación y reinicia el opt-in.
2. **Casilla de la clínica:** "El paciente autorizó recibir recordatorios por WhatsApp". Al marcarla se guardan `optin_atestado_por` y `optin_atestado_en` y se registra en auditoría. **Sin casilla no se envía nada por API.**
3. **Primer mensaje (plantilla `optin_v1`, un solo intento):** neutro, **sin nombre del paciente ni fecha**, con botones Sí / No. `optin_estado` pasa a `pendiente`.
4. **Respuesta:** Sí → `aceptado`; No → `rechazado`. Sin respuesta, sigue `pendiente`: **no recibe recordatorios automáticos y no se insiste.** Si responde dentro de la ventana de 24 h, se puede enviar un acuse breve sin plantilla.
5. **Baja:** el botón "Dejar de recibir" de cualquier mensaje crea una fila en `baja_whatsapp` y bloquea el envío para ese teléfono en **todas** las clínicas. El sistema **nunca** la revierte solo.
6. **Reactivación:** solo si el paciente lo pide en la clínica. Personal autorizado (sección 5) marca `reactivada_en` (auditado), vuelve a marcar la casilla y el sistema repite el paso 3 (se vuelve a pedir el Sí).

### 7.2 Plantillas de la plataforma (aprobadas por Meta, versionadas)
- `optin_v1`: "{{APP_NAME}}: ¿aceptas recibir notificaciones de tus citas por WhatsApp de parte de {clínica} y {médico}? Puedes dejar de recibirlas cuando quieras." Botones: **Sí · No**.
- `recordatorio_v1`: recordatorio de consulta con `{paciente}`, `{medico}`, `{clinica}`, `{fecha}`, `{hora}`, `{sala}`, `{politica_cancelacion}`, `{contacto_medico}` (opcional) y `{enlace_mapa}`. Botones: **Confirmar · Cancelar · Dejar de recibir**.
- **La estructura es fija:** las clínicas solo personalizan el *valor* de las variables. Cambiar el texto de una plantilla exige una versión nueva y una aprobación nueva de Meta.
- Tono transaccional; **sin tipo de tratamiento ni datos clínicos**. Verificar que Meta mantenga ambas como *utility* (si las reclasifica como marketing, el costo sube) y revisar los límites vigentes de variables y botones.

### 7.3 Envío automático
- Job del worker, idempotente: para citas (`consulta`/`procedimiento`) en `pendiente_envio` con paciente `aceptado`, envía `recordatorio_v1` el **día anterior a una hora configurable** (por defecto 10:00, hora de la clínica); las citas creadas después de esa hora se envían de inmediato si faltan más de 2 horas.
- Al aceptarlo Meta, la cita pasa a `enviado`. Si falla (`fallido`), vuelve a `pendiente_envio` y se notifica al personal (`envio_fallido`).
- **Confirmar** → `confirmada` (`confirmado_en`). **Cancelar** → `cancelada` (`cancelada_por = paciente`), libera el espacio y avisa al personal.
- Citas `enviado` sin confirmar: alerta a asistentes y admin cada **4 h** (configurable), solo en horario laboral y con tope de frecuencia (notificación en app y correo sin datos de pacientes).
- El texto libre del paciente se ignora; el número de la plataforma no se usa para conversar.

### 7.4 Lista manual (`wa.me`)
Lista diaria en el panel; sin enlace de confirmación (el personal actualiza el estado a mano). Para clínicas con WhatsApp activo incluye solo pacientes **sin** opt-in aceptado (excluye `rechazado`, con baja global o `no_enviar_recordatorios`); para clínicas con `notificaciones_whatsapp = false` incluye todas las citas del día salvo `no_enviar_recordatorios` (confirmar con el propietario si la baja global también aplica aquí). Usa el texto libre `plantilla_recordatorio` de la clínica. Enlace `https://wa.me/52XXXXXXXXXX?text=<mensaje codificado>`; validar el formato con números reales de prueba (y el del número en la API de Meta: `52…` frente a `521…`).

### 7.5 Costos y calidad del número
La plataforma paga a Meta; `mensaje_whatsapp` mide el consumo por clínica y mes. La calidad del número (bloqueos y reportes recientes) se revisa a mano en WhatsApp Manager; automatizarla (tope diario de opt-ins, aumento gradual, aviso por webhook, pausa automática, métricas por clínica) queda para después.

---

## 8. Plan de trabajo

### Fase 1 — Backend núcleo
1. ✅ **Hecho.** Modelos y migraciones (0004, 0005), RLS, función de login, pruebas de BD.
2. ✅ **Hecho.** Operador (`/api/operador/*`), activación que crea `personal` y `aceptacion_legal`, invitaciones a usuarios existentes, contexto de clínica en la sesión, migración 0006 y pruebas.
3. ✅ **Hecho.** RBAC con la matriz como datos (`rbac.py`), dependencia `requerir(accion)` (`authz.py`) y pruebas parametrizadas.
4. ✅ **Hecho.** `/api/personal` y `/api/salas` con límite de plan, invitaciones del personal, un solo admin por clínica, pruebas de roles, tope, duplicados, IDOR y corte de sesión al desactivar.
5. **Siguiente: pacientes.** Plan (borrador, confirmar las decisiones de la sección 0):
   1. `/api/pacientes`: crear, listar, ver, editar y borrado lógico (`eliminado_en`).
   2. Nombre y teléfono cifrados; `telefono_idx` con la clave de plataforma sobre el teléfono normalizado a E.164.
   3. **Confirmación obligatoria del teléfono** al crear; cambiarlo la repite y reinicia el opt-in a `sin_solicitar`.
   4. Aviso de teléfono repetido en la misma clínica (no bloquea).
   5. Casilla de autorización (marcar y desmarcar) y reactivación tras baja; lo que depende de `baja_whatsapp` (Fase 2) queda como gancho.
   6. Vínculo paciente-médico validando en la aplicación que el vinculado sea **médico activo** de la clínica.
   7. Visibilidad: admin y asistente ven todos; el médico, solo los vinculados (si crea un médico, queda vinculado).
   8. Búsqueda por nombre: descifrar en memoria la lista visible y filtrar, sin `LIKE`.
   9. Auditoría en cada mutación (quién atestó, confirmó el teléfono o reactivó; sin datos personales en la metadata). Pruebas: IDOR, visibilidad por rol, teléfono sin confirmar, cambio de teléfono, nombre solo con espacios, y que la BD guarde solo texto cifrado en los campos 🔒.
6. Agenda: crear, mover y cancelar citas, bloqueos, tipos, exclusiones, estados, comentarios. (Incluye decidir qué pasa con las citas de personal desactivado.)
7. Auditoría en toda mutación (revisión transversal).
8. Scripts de rotación por lotes (reenvolver DEKs, recifrar).
9. Recuperación de contraseña (sin revelar si la cuenta existe; `EmailProvider` con Resend de pruebas) y envío automático de invitaciones.

**Listo cuando:** la matriz RBAC pasa completa; una prueba IDOR entre clínicas falla como debe; una prueba de concurrencia no permite doble reserva; crear o cambiar un paciente sin confirmar el teléfono falla; y la BD muestra solo texto cifrado en los campos 🔒.

### Fase 2 — WhatsApp, recordatorios y correo (parte backend)
0. Migración **0007** (`baja_whatsapp`, `mensaje_whatsapp`, `webhook_evento` y funciones de BD para el webhook).
1. Interfaces `ReminderChannel` y `WhatsAppClient`; `MetaCloudApiChannel` (con cliente simulado en pruebas) y `WaMeLinkChannel`; validación del formato con un número de prueba de Meta (la normalización E.164 ya existe desde el paso 5).
2. Opt-in: casilla por paciente en la API, envío de `optin_v1` (un solo intento), estados y comprobaciones previas al envío (sección 6).
3. Webhook: verificación, firma, idempotencia, estados de entrega, respuestas con botones (validando el teléfono remitente), baja global, acuses breves.
4. Recordatorios automáticos (job idempotente, `recordatorio_v1`), transiciones de estado, fallos, alertas de citas sin confirmar y resumen diario con Resend (remitente de pruebas en local); notificaciones en app.
5. Lista manual `wa.me` y correo con conteo y enlace al panel.
6. Medición de consumo por clínica y mes.
7. Pruebas: firma inválida; respuestas repetidas (idempotencia); teléfono remitente distinto del paciente; una baja bloquea envíos en todas las clínicas; la reactivación solo por personal autorizado; sin casilla no se envía el opt-in; sin `aceptado` no se envía el recordatorio; clínica con `notificaciones_whatsapp = false` no envía por API; correos sin datos personales; el webhook no deja teléfonos en logs.

**Listo cuando:** el flujo completo funciona en local con el cliente simulado: paciente con casilla → opt-in Sí → recordatorio → botón Confirmar actualiza la cita → sin respuesta genera alerta; una baja bloquea los envíos. La prueba real con el número de prueba de Meta se hace cuando exista un túnel temporal o el despliegue en VPS.

---

## 9. Decisiones abiertas (backend)

| Tema | Por defecto |
|---|---|
| Paso 5: médico obligatorio al crear paciente (admin/asistente) | Sí, al menos uno; si crea un médico, queda vinculado a sí mismo |
| Paso 5: desmarcar la casilla de autorización | Sí; vuelve a `sin_solicitar` |
| Paso 5: borrado lógico de pacientes | Lo hace y lo ve solo el admin |
| Paso 5: normalización E.164 del teléfono | Se adelanta al paso 5 (México `+52`), para un `telefono_idx` consistente |
| Horario del médico | Bloqueos puntuales dentro del horario de la clínica; un bloqueo de varios días es un solo evento con el rango completo |
| Retención de pacientes y citas | Borrado lógico y purga configurable (plazo por definir) |
| Hora de envío automático | Día anterior a las 10:00 (hora de la clínica), configurable; citas creadas tarde: inmediato si faltan más de 2 h |
| Cobro de mensajes de WhatsApp | Propuesta: costo de Meta + 30%, o paquete incluido; la medición ya está prevista |
| Calidad del número | Revisión manual en WhatsApp Manager; automatización después |
| Baja global en clínicas sin WhatsApp (lista manual) | Por confirmar (sección 7.4) |
| Acceso al panel del operador | Subdominio aparte con Cloudflare Access (VPS) |
| Datos legales de la clínica | Los captura el operador; evaluar moverlos al admin si genera desconfianza |
| Login de personal de clínica suspendida | Hoy entra pero sin contextos; decidir si el login debe fallar |
| Entrega de invitaciones | Manual (token único en `POST /clinicas` y en `POST /api/personal/invitaciones`); correo automático en el paso 9 |
| Citas de personal desactivado | Se decide en el paso 6 (hoy no se tocan) |
| Nombre y dominio | Provisional `medi-clinic` / `localhost`; viven solo en `config.py` |

**Decididas en el paso 4:** las invitaciones pendientes de médico cuentan para el tope del plan; aviso al 80 %; desactivar personal corta sus sesiones; solo el admin desactiva, reactiva y edita a otros; el rol `admin` no se invita.

---

## 10. Primer mensaje para iniciar

> Lee este documento completo, **empezando por la sección 0**. Responde con: (1) resumen del proyecto y de dónde vamos en máximo 8 líneas, (2) las dudas que **bloqueen** el paso 5 de la Fase 1 (solo las bloqueantes; las decisiones de la sección 0 se asumen por defecto si digo "defaults") y el plan de ese paso en 5–10 líneas. **No escribas código todavía.** Pídeme los archivos que necesites ver.