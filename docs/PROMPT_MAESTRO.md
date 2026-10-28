# PROMPT MAESTRO — {{APP_NAME}}: agenda B2B para clínicas con recordatorios

> Documento autocontenido. Pégalo al inicio de una sesión nueva (p. ej. Claude Code) y trabaja por fases.
> Marcadores pendientes: `{{APP_NAME}}` y `{{DOMINIO}}` (nombre y dominio aún sin definir; úsalos en código, configuración y textos para que renombrar sea trivial). Nombre provisional de desarrollo: **medi-clinic**; dominio: `localhost`. Ambos viven solo en `backend/app/config.py`.
> **Última actualización:** 2026-10-27. Ver la sección 0 para el estado actual: continúa desde el paso indicado ahí.

---

## 0. Estado actual y decisiones de implementación

**Dónde vamos:** Fase 0, pasos 0.1 a 0.4 hechos (0.4 verificado con el CI en verde). **Paso 0.5 (autenticación base) en curso:** hechos el bloque 1 (migración 0002) y el bloque 2 (primitivas de auth), con `make check` pasando. **Siguiente: bloque 3.**

### 0.1 Pasos completados
| Paso | Resultado |
|---|---|
| 0.1 Repo y estándares | Estructura de la sección 10, `pyproject.toml` (ruff, mypy strict, pytest), `.pre-commit-config.yaml` (ruff, ruff-format, mypy, gitleaks), `.gitignore`, README, `Makefile`. |
| 0.2 Docker Compose local | `backend/Dockerfile` (python:3.13-slim, uv, usuario `app` uid 10001 sin root; solo copia `pyproject.toml`, `uv.lock` y `app/`), `infra/docker-compose.yml` (`db` PostgreSQL 16 solo en red interna, `api` en `127.0.0.1:8000`, contenedor de solo lectura), `GET /health`, `infra/scripts/gen-local-secrets.sh`. |
| 0.3 Módulo de cifrado | `backend/app/crypto/`: `KeyProvider` + `FileKeyProvider`, DEK envuelta (`envelope.py`), cifrado de campos AES-256-GCM con AAD (`fields.py`), índice ciego (`blind_index.py`), rotación de KEK (`rewrap_dek`) y de DEK (`reencrypt`). |
| 0.4 Base de datos | SQLAlchemy 2 **async** + psycopg 3 (`app/db/session.py`: `make_engine(rol)`, `clinic_session` que fija `app.clinica_id` con `set_config(..., true)`). Alembic async (`env.py` migra con el rol `migrador`). Roles en `infra/db/roles.sql` + `init-roles.sh` (se ejecuta al crear el volumen). Migración 0001: `btree_gist` y tabla `_rls_demo` con RLS forzada. Pruebas de aislamiento en `tests/db/test_rls.py`. `.github/workflows/ci.yml` mínimo (Postgres 16, roles, migraciones, `make check`). |
| 0.5 (parcial) | **Bloque 1:** migración `0002_auth.py` (tablas `llave_plataforma`, `usuario`, `codigo_recuperacion`, `sesion`, `invitacion`, `intento_login`, `auditoria`, con permisos por rol). **Bloque 2:** `app/auth/` con `passwords.py` (argon2id, mín. 12 y máx. 128 caracteres, `verify_dummy`), `totp.py` (`verify_totp` devuelve el paso coincidente o `None`; ventana ±1), `recovery.py` (10 códigos de un solo uso, solo hash), `tokens.py` (256 bits, SHA-256) y `tests/auth/test_auth_primitives.py`. |

### 0.2 Pendiente del paso 0.5 (en este orden)
1. **Bloque 3:** migración `0003` (columna `usuario.totp_ultimo_paso bigint` para impedir reutilizar un código TOTP), límite de intentos (sobre `intento_login`) y servicio de auditoría.
2. **Bloque 4:** endpoints: activar invitación (fija contraseña + activa 2FA + muestra códigos de recuperación), login en dos pasos (contraseña → TOTP; sesión intermedia con `mfa_ok=false`), logout, `/me`. Cookie `HttpOnly; Secure; SameSite=Lax`, CSRF en operaciones que cambian estado, respuestas que no revelan si la cuenta existe (usar `verify_dummy`), auditoría en cada mutación.
3. **Bloque 5:** script del primer operador (`docker compose exec api python -m app.scripts.bootstrap_platform`: crea la DEK de plataforma, la envuelve con la KEK, guarda en `llave_plataforma` y pide email y contraseña del operador por terminal; en pruebas y CI se hace con una fixture). Montar `db_app_password` y `kek_v1` en el servicio `api` (el usuario 10001 debe poder leerlos) y **copiar `alembic/` y `alembic.ini` a la imagen** si se quieren correr migraciones dentro del contenedor.
4. Pruebas de auth en CI: login, 2FA, bloqueo por intentos, invitación de un solo uso, sin datos personales en logs.

### 0.3 Decisiones tomadas durante la implementación (prevalecen sobre el resto del documento si chocan)
- **Python 3.13**, gestor **uv**. Dependencias: `fastapi`, `pydantic-settings`, `uvicorn`, `cryptography`, `sqlalchemy`, `alembic`, `psycopg[binary]`, `argon2-cffi`, `pyotp`; dev: `ruff`, `mypy`, `pytest`, `pytest-asyncio` y el cliente de pruebas de Starlette (verificar en `pyproject.toml` si es `httpx` o `httpx2`). Dependencias nuevas se agregan con `uv add`.
- **BD async** (`postgresql+psycopg://`, `AsyncSession`).
- **Las pruebas de BD corren solo en CI**: `db` está en una red `internal: true` y no se publica al host. En local se saltan (`skipif APP_TEST_DB != "1"`); el CI define `APP_TEST_DB=1` y `APP_DB_HOST=localhost`. No hay `docker-compose.dev.yml`.
- **Sin Mailpit**: Resend por API HTTP. Las pruebas de correo usan un cliente simulado (interfaz de proveedor de correo).
- **Secretos como archivos** en `./secrets/` (permisos 600, ignorados por git), nunca en variables de entorno. Archivos: `db_password` (superusuario `medi_admin`, solo crea los roles), `db_migrador_password`, `db_app_password`, `db_operador_password`, `kek_v1`… `Settings.database_url(rol)` lee `db_<rol>_password`. **No hay `.env.example`**; las variables de entorno llevan prefijo `APP_` (`APP_APP_NAME`, `APP_DOMINIO`, `APP_ENTORNO`, `APP_SECRETS_DIR`, `APP_KEK_ACTIVE_VERSION`, `APP_DB_HOST` [por defecto `db`], `APP_DB_PORT`, `APP_DB_NAME`, `APP_SESSION_IDLE_HOURS`, `APP_SESSION_MAX_HOURS`, `APP_INVITACION_HORAS`).
- **Sesiones:** caducidad por inactividad de **8 h** y tope absoluto de **24 h** (la plataforma se deja abierta buena parte del día). Invitaciones: **72 h**. Valores en `config.py`.
- **Límite de intentos en la base de datos** (tabla `intento_login`, con `clave_hash` = HMAC de IP o cuenta, nunca el dato en claro), no en memoria.
- **TOTP:** 6 dígitos, paso de 30 s, ±1 paso. Se guarda el último paso aceptado (`totp_ultimo_paso`) para no reutilizar códigos. **Códigos de recuperación:** 10, de un solo uso, solo hash.
- **Roles de BD:** `migrador` (dueño de la BD, el esquema y las tablas), `app` (CRUD por defecto sobre lo que cree el migrador; sin ser dueño, para que RLS aplique), `operador` (sin permisos por defecto; se otorgan por tabla en las migraciones: hoy `usuario`, `invitacion`, `llave_plataforma` [lectura] y `auditoria` [insertar]). `auditoria` es de solo inserción para `app`; `llave_plataforma` es de solo lectura para `app`.
- **`_rls_demo` se queda hasta la Fase 1**, cuando existan las tablas reales con el mismo patrón de RLS (`nullif(current_setting('app.clinica_id', true), '')::uuid`). Se elimina entonces.
- `invitacion` guarda también `email` cifrado (además de `email_idx`) para poder crear el usuario al activarla. `invitacion.clinica_id` no tiene llave foránea hasta que la Fase 1 cree `clinica`. La **membresía** (usuario + clínica + rol) se crea en la Fase 1. `auditoria` no tiene RLS todavía (los eventos de login no tienen clínica); la Fase 1 lo agrega para los eventos con `clinica_id`.
- **Valores cifrados:** columnas `BYTEA` con formato binario `formato(1) | versión_dek(4) | nonce(12) | cifrado+tag`; el encabezado va dentro del AAD. DEK envuelta: `formato(1) | versión_kek(4) | nonce(12) | cifrado+tag`, con AAD de contexto (`clinica|<uuid>|v<n>` o `plataforma|v<n>`).
- **AAD de campos:** `tabla|columna|clinica_id|fila_id`; datos de plataforma usan `plataforma` en lugar de la clínica (`FieldContext(clinica_id=None)`).
- **Índice ciego:** HMAC-SHA256 con clave derivada por HKDF desde la DEK y la columna. Si se rota la DEK, los índices se recalculan junto con el recifrado. `normalize_email` (strip + minúsculas) ya existe; la normalización de teléfonos (E.164) va en la Fase 2.
- **Rotación:** la biblioteca incluye `rewrap_dek` y `reencrypt`. Los **scripts por lotes sobre la base de datos** se escriben en la Fase 1.
- **Docs de la API** (`/docs`, `/openapi.json`) solo cuando `APP_ENTORNO=local`.
- Las migraciones aún no se corren en local (la imagen de `api` no incluye `alembic/` ni los secretos); se verifican en CI.

### 0.4 Convenciones de trabajo con el propietario
- Comandos diarios con `make`: `help`, `check` (ruff + pytest + mypy), `format`, `up`, `down`. Lo que se hace una sola vez (secretos, `pre-commit install`, migraciones) va documentado en el README, no en el Makefile.
- El propietario trabaja en Ubuntu, repo en `~/Documents/personal/medi-clinic`, con Docker Compose v2, uv y pre-commit instalados. El puerto 8000 está libre.
- **La IA no ejecuta código ni revisa el repo local.** El propietario revisa y corre todo paso a paso en su máquina. La IA entrega **solo los archivos creados o modificados, uno por uno**, con su ruta, e indica qué comandos correr. Si necesita ver un archivo existente antes de modificarlo, lo pide.
- Al terminar cada paso (y cada bloque), el propietario confirma que `make check` pasa; los cambios de BD se confirman además con el CI en verde en GitHub (las pruebas de `tests/db` deben salir *passed*, no *skipped*).
- Prefiere explicaciones muy cortas; no domina terminología de seguridad: explicar conceptos nuevos en pocas líneas (KEK = llave maestra fuera de la base de datos; DEK = llave de datos por clínica; AAD = etiqueta que ata el dato a su fila; índice ciego = huella para buscar sin descifrar; RLS = la base de datos misma filtra las filas por clínica).

---

## 1. Rol y reglas de trabajo (para la IA)

1. Responde en español, de forma concisa. Explicaciones cortas.
2. **Antes de crear o modificar código, pide el contexto que falte** y confirma el plan del paso en 5–10 líneas. Después implementa.
3. Trabaja **una fase y un paso a la vez**. Al terminar cada paso informa: qué cambió, cómo probarlo y cuál es el siguiente paso.
4. **Nunca** guardes, registres en logs, pongas en URLs ni muestres datos personales en claro (sección 8). Sin datos reales en pruebas ni ejemplos.
5. Si algo de este documento choca con otra cosa, avisa. No cambies decisiones en silencio.
6. No agregues funciones fuera de alcance (sección 5) ni dependencias nuevas sin justificarlas en una línea.
7. Mantén todo **modular** con interfaces: canal de recordatorios, proveedor de claves, proveedor de correo, pagos.
8. Escribe pruebas junto con el código, sobre todo de autorización, aislamiento entre clínicas y cifrado.
9. Los textos legales son borradores sin revisión de abogado; márcalos así.

---

## 2. Producto en una página

Aplicación web **B2B** para clínicas y consultorios pequeños de México (empezando por dentistas) que hoy llevan sus citas en Excel o papel.

- Agenda por médico (y por sala, opcional) con roles.
- Recordatorios de cita a pacientes **sin API de WhatsApp en el MVP**: la app genera, por cada cita, un enlace `wa.me` con el mensaje ya escrito; la secretaria da clic y envía desde el WhatsApp de la clínica.
- Enlace de confirmación/cancelación para el paciente, sin cuenta.
- Resumen diario por correo (sin datos de pacientes) y alertas de citas sin confirmar.
- Alta **manual** de clínicas por el operador de la plataforma (no hay registro público).
- Seguridad de datos de pacientes como prioridad máxima; sin historial médico ni documentos.
- Piloto: 2 consultorios gratis. Modelo futuro: suscripción por rango de médicos; recordatorios por WhatsApp API como módulo de pago (después).

---

## 3. Glosario (usar estos nombres en código, UI y datos)

| Término | Significado |
|---|---|
| **Clínica** | Tenant. Cliente de la plataforma (puede ser un solo médico). |
| **Sala** | Habitación/cuarto donde se da la consulta dentro de la clínica. Opcional. |
| **Usuario** | Identidad de login (global). |
| **Membresía** | Usuario + clínica + rol + perfil. Un usuario puede tener varias, con perfil distinto en cada clínica. |
| **Admin** | Rol. Uno solo por clínica. |
| **Asistente** | Rol. Secretaría/recepción. Varios por clínica. |
| **Médico** | Rol. Cuenta para el límite del plan. |
| **Paciente** | Registro dentro de una clínica. No es usuario; no tiene login. |
| **Cita** / **Bloqueo** | Eventos de agenda de un médico. |
| **Operador** | Dueño de la plataforma. Rol global separado de los roles de clínica. |

---

## 4. Decisiones cerradas

| Tema | Decisión |
|---|---|
| Stack backend | Python 3.13, FastAPI, SQLAlchemy 2 **async** + psycopg 3 + Alembic, Pydantic v2, PostgreSQL 16 |
| Stack frontend | React + TypeScript (Vite), mismo origen que la API (Caddy enruta `/api`) |
| Hosting | VPS único, Docker Compose, Caddy (HTTPS automático) |
| Dominio / DNS | Cloudflare (registro y DNS) |
| Correo | Resend (transaccional). Ningún correo incluye datos de pacientes |
| Recordatorios MVP | Enlace `wa.me` desde el WhatsApp de la clínica. Canal detrás de una interfaz para cambiarlo luego por la API oficial de Meta |
| Consentimiento del paciente | La app **no** lo recaba. La clínica es responsable (términos y aviso de privacidad). Decisión del propietario, sin validación legal; el diseño deja campos opcionales para añadirlo después |
| Alta de clínicas | Manual por el operador. Sin registro público |
| Verificación de cédula | No la hace la plataforma. Queda como responsabilidad de la clínica en los términos |
| Planes | 5, 10, 20 y 50 médicos; más de 50, contacto. Solo los **médicos** cuentan; los asistentes no |
| Suscripción | Manual y gratuita al inicio, pero con campos de plan, estado y vigencia en la base desde el día 1 |
| Datos de salud | Prohibidos en la app (diagnósticos, historial, archivos). Comentarios de cita: texto corto, con aviso en la UI |
| Operador | No puede ver datos de pacientes (ni por permisos de aplicación ni por permisos de base de datos) |
| Cifrado | A nivel de campo, en el backend (sección 8) |

---

## 5. Fuera de alcance del MVP

WhatsApp API oficial, pagos y cobro automático, archivos/documentos, historial o expediente clínico, registro público de clínicas, portal o app para pacientes, marketplace o anuncios, sincronización con Google/Outlook Calendar, app móvil nativa, analítica de terceros.

La estructura debe dejar el camino listo para: canal de WhatsApp API, pagos, consentimiento del paciente.

---

## 6. Roles y permisos

| Acción | Operador | Admin | Asistente | Médico |
|---|---|---|---|---|
| Crear clínica, invitar admin, plan/estado/vigencia, suspender | sí | no | no | no |
| Ver datos de pacientes y citas | **no** | todos | todos | solo los suyos |
| Crear/editar/cancelar citas | no | sí | sí | sí (las suyas) |
| Bloquear agenda propia | no | sí (de cualquier médico) | sí (de cualquier médico) | sí (la suya) |
| Agregar pacientes | no | sí | sí | sí |
| Vincular pacientes a otros médicos | no | sí | sí | no |
| Agregar médicos | no | sí | sí | no |
| Agregar asistentes | no | sí | no | no |
| Crear/editar salas | no | sí | no | no |
| Configurar clínica (plantilla, política, mapa) | no | sí | no | no |
| Borrar (pacientes, citas, personal) | no | sí | no | no |

Reglas:
- La matriz vive **como datos** en un solo módulo de autorización y las pruebas se parametrizan contra ella.
- Un médico solo ve los pacientes vinculados a él. Admin y asistente ven todos los de la clínica y pueden vincularlos a otros médicos.
- Los pacientes pertenecen a **una** clínica y nunca se comparten entre clínicas.
- Un usuario puede tener membresías en varias clínicas, con rol y perfil independientes. Al entrar elige el contexto.

---

## 7. Modelo de datos (UUID como identificadores; nunca enteros secuenciales)

Los campos marcados 🔒 van cifrados (sección 8). Fechas y horas en claro. Las tablas marcadas ✅ ya existen (migración 0002).

- ✅ **usuario**: id, email 🔒, email_idx (índice ciego, único), password_hash (argon2id), totp_secret 🔒, totp_activo, es_operador, activo, ultimo_login, creado_en. *(0003 agrega `totp_ultimo_paso`.)*
- ✅ **codigo_recuperacion**: id, usuario_id, codigo_hash (único), usado_en.
- ✅ **sesion**: id, usuario_id, token_hash, mfa_ok (false = contraseña verificada, falta TOTP), creado_en, ultimo_uso, expira_en, ip.
- ✅ **invitacion**: id, email 🔒, email_idx, clinica_id (sin FK hasta la Fase 1), rol, token_hash, expira_en, usada_en, creada_por, creado_en.
- ✅ **intento_login**: id, clave_hash (HMAC de IP o cuenta), tipo, creado_en.
- ✅ **auditoria**: id, clinica_id, actor_usuario_id, accion, entidad, entidad_id, ip, creado_en, metadata (sin datos personales). Cubre toda mutación. Solo inserción para `app`.
- ✅ **llave_plataforma**: version, dek_wrapped, activa, creado_en. DEK de plataforma (cifra los datos de `usuario` e `invitacion`), envuelta con la KEK. `app` solo lee.
- **clinica**: id, nombre (en claro), zona_horaria (IANA, por defecto `America/Mexico_City`), plan (`p5|p10|p20|p50|custom`), estado (`prueba|activa|suspendida`), vigencia_hasta, google_maps_url, politica_cancelacion, plantilla_recordatorio, horario_laboral, dek_wrapped, dek_version, creado_en.
- **membresia**: id, usuario_id, clinica_id, rol (`admin|asistente|medico`), nombre 🔒, contacto_preferido 🔒 (opcional, médicos), activo. Único (usuario, clínica). **Índice único parcial: un solo admin activo por clínica.**
- **sala**: id, clinica_id, nombre, activa.
- **paciente**: id, clinica_id, nombre 🔒, telefono 🔒 (E.164), telefono_idx, no_enviar_recordatorios, consentimiento_estado (por defecto `desconocido`), consentimiento_fecha, consentimiento_fuente (estos tres no se exigen en el MVP), creado_por, eliminado_en.
- **paciente_medico**: paciente_id, membresia_id (médico). Define la visibilidad del médico.
- **evento_agenda** (cita y bloqueo en una sola tabla): id, clinica_id, tipo (`cita|bloqueo`), medico_membresia_id, sala_id (nulo), paciente_id (nulo en bloqueos), rango (`tstzrange`), estado (`pendiente_envio|enviado|confirmada|cancelada`), comentario 🔒 (máx. 500 caracteres), cancelada_por (`paciente|personal`), enviado_en, confirmado_en, creado_por, creado_en, actualizado_en.
  - Restricción de exclusión (extensión `btree_gist`, ya instalada) sobre `(medico, rango)` donde estado ≠ cancelada. Así una cita no puede traslaparse con otra cita ni con un bloqueo.
  - Segunda exclusión sobre `(sala_id, rango)` para citas no canceladas con sala.
- **token_cita**: id, evento_id, token_hash (SHA-256), expira_en (hasta el inicio de la cita), creado_en.
- **notificacion**: id, clinica_id, destinatario_membresia_id, tipo, evento_id, creada_en, leida_en. Sin datos personales en el contenido.
- **aceptacion_legal**: id, clinica_id, usuario_id, documento (`terminos|aviso`), version, aceptado_en, ip.

Todas las tablas con datos de clínica llevan `clinica_id` y Row-Level Security.

---

## 8. Seguridad (no negociable desde la Fase 0)

### 8.1 Cifrado de campos (backend)
- **Jerarquía de claves:** KEK (maestra) → DEK por clínica (más una DEK de plataforma) → clave de índice ciego derivada con HKDF.
- La **KEK nunca está en la base de datos, ni en respaldos, ni en el repositorio**. Vive en un archivo o secreto con permisos mínimos, y se respalda aparte, fuera de línea. Perderla significa perder todos los datos.
- **AES-256-GCM** con la librería `cryptography`. Nonce aleatorio de 12 bytes por valor. Formato: `versión_formato | versión_clave | nonce | texto_cifrado+tag`.
- **AAD** en cada valor: `tabla|columna|clinica_id|fila_id`, para impedir que se intercambien textos cifrados entre filas o clínicas.
- **Índice ciego** (HMAC-SHA256) para búsquedas exactas (teléfono, email de login), con valores normalizados (E.164, minúsculas) y clave derivada por clínica.
- Búsqueda por nombre: descifrar en memoria la lista del médico y filtrar ahí. Sin `LIKE` sobre campos cifrados.
- Interfaz `KeyProvider` con `FileKeyProvider` ahora y `KmsKeyProvider` (futuro). Soporte de **rotación**: versión de clave en cada valor; script para reenvolver DEKs y otro para recifrar por lotes.
- Límite honesto, para documentar: si alguien compromete el servidor en ejecución, puede descifrar. Se mitiga con el resto de esta sección.

### 8.2 Autenticación y sesiones
- Contraseñas con **argon2id**, mínimo 12 caracteres (máximo 128).
- **2FA TOTP obligatorio** para admins y operador; opcional para los demás. Códigos de recuperación (10, un solo uso) guardados con hash. Un código TOTP no se puede reutilizar.
- Sesiones del lado del servidor, cookie `HttpOnly; Secure; SameSite=Lax`, **8 h de inactividad y 24 h máximo absoluto**, protección CSRF en operaciones que cambian estado.
- Invitaciones de un solo uso con vencimiento (72 h) para activar cuenta (fijar contraseña y activar 2FA). Recuperación de contraseña sin revelar si la cuenta existe.
- Límite de intentos y bloqueo temporal por IP y por cuenta en login, recuperación, invitación y endpoints públicos (guardado en la base de datos).

### 8.3 Autorización y aislamiento
- Una única capa de autorización centralizada. Nada de comprobaciones dispersas.
- Cada consulta filtra por `clinica_id`. **Row-Level Security** en PostgreSQL como segunda barrera (`app.clinica_id` por transacción).
- Tres roles de base de datos: **migrador** (dueño de tablas), **app** (sin ser dueño, para que RLS aplique) y **operador** (permisos solo sobre `clinica`, `usuario`, `invitacion` y lo mínimo para auditar; sin acceso a pacientes ni agenda).
- IDs no secuenciales. Respuestas uniformes (404) para recursos ajenos, para evitar enumeración.

### 8.4 Datos y privacidad
- Prohibido guardar historial médico, diagnósticos o archivos. Aviso visible en el campo de comentarios, límite de 500 caracteres, sin subida de archivos.
- **Logs sin datos personales:** nunca registrar cuerpos de petición; redactar teléfonos, nombres y correos. Si se usa seguimiento de errores, con filtrado activo.
- Sin scripts de terceros en el frontend. Sin analítica por ahora. Sin datos personales en `localStorage`, `sessionStorage` ni URLs.
- Cabeceras de seguridad: CSP estricta, HSTS, `X-Content-Type-Options`, `Referrer-Policy`, `frame-ancestors 'none'`.

### 8.5 Enlace público de confirmar/cancelar
- Token aleatorio de al menos 256 bits (`secrets.token_urlsafe(32)`), guardado solo como hash, con vencimiento.
- La página muestra únicamente clínica, médico, fecha, hora, mapa y política de cancelación. **Sin nombre completo ni teléfono del paciente.**
- Respuesta idéntica para token inválido o vencido. Límite de intentos. Acciones idempotentes.

---

## 9. Recordatorios y correo

### 9.1 Mensaje de recordatorio (plantilla por clínica)
Variables: `{paciente}`, `{medico}`, `{clinica}`, `{fecha}`, `{hora}`, `{sala}`, `{politica_cancelacion}`, `{contacto_medico}` (opcional), `{enlace_confirmacion}`, `{enlace_mapa}`.
- Tono neutral y transaccional. **No incluir tipo de tratamiento ni datos clínicos.**
- Interfaz `ReminderChannel` con `WaMeLinkChannel` (MVP) y `MetaCloudApiChannel` (futuro, sin implementar).
- Enlace: `https://wa.me/52XXXXXXXXXX?text=<mensaje codificado>`. **Validar con números reales de prueba** que el formato funciona.

### 9.2 Flujo diario
1. Lista del día (o del día siguiente) con las citas por recordar, con botón por paciente. Excluye pacientes con `no_enviar_recordatorios`.
2. Al enviar: estado `pendiente_envio` → `enviado`. Confirmación o cancelación por el enlace público.
3. Citas `enviado` sin confirmar: alerta a asistentes y admin cada **n horas** (por defecto 4), solo en horario laboral de la clínica, con tope de frecuencia. Va como notificación en la app y correo sin datos de pacientes.
4. Cancelación por el paciente: libera el espacio y notifica al personal.

### 9.3 Correo con Resend
- Dominio de envío verificado en Resend: SPF, DKIM y DMARC (empezar en `p=none` y subir a `quarantine`). Registros en Cloudflare como **solo DNS** (sin proxy).
- Correos: invitaciones, recuperación de contraseña, resumen diario y alertas. Contienen **solo conteos y un enlace al panel protegido por login.**
- Clave de API en secretos, nunca en el repositorio. Revisar límites del plan gratuito vigente.
- Prueba automática (snapshot) que verifique que ningún correo incluye nombres ni teléfonos.

---

## 10. Arquitectura y repositorio

```
/backend    FastAPI (app/, crypto/, db/, auth/, authz/, agenda/, reminders/, jobs/, alembic/, tests/)
/frontend   React + TypeScript (Vite)
/infra      docker-compose, db/ (roles), Caddyfile, scripts de respaldo/restauración, hardening
/docs       este prompt, runbooks, borradores legales
/.github    CI
```

- Un contenedor `api`, uno `worker` (jobs programados: resumen diario y alertas), `db` (PostgreSQL, **solo red interna**), `caddy` (HTTPS y estáticos del frontend).
- Frontend y API en el mismo origen: sin CORS abierto.
- Tipos del frontend generados desde el esquema OpenAPI del backend.
- Calendario: elegir librería con **licencia compatible** (las vistas por recurso de FullCalendar son premium; evaluar alternativas como react-big-calendar).
- Hora: guardar en UTC (`timestamptz`), mostrar en la zona de la clínica. Granularidad mínima de cita: 15 minutos.

---

## 11. DevOps (VPS)

Endurecimiento mínimo del servidor:
- Usuario sin privilegios, SSH solo con llaves, sin acceso root por SSH.
- Firewall: abierto solo 80/443 (y 22 limitado). `fail2ban`. Actualizaciones de seguridad automáticas.
- Contenedores sin root. Secretos en archivos con permisos 600 fuera del repositorio.
- Cloudflare: registro A con proxy activo, SSL en modo **Full (strict)**. Opcional: limitar el origen a las IP de Cloudflare.
- Reglas de límite de peticiones en Cloudflare para login y endpoints públicos, además del límite en la aplicación.

Respaldos:
- `pg_dump` nocturno, cifrado con `age` (la llave privada guardada fuera de línea) y subido a almacenamiento **fuera del VPS** (Cloudflare R2 o Backblaze B2; decisión abierta).
- Retención sugerida: 7 diarios, 4 semanales, 6 mensuales. **Prueba de restauración mensual** en una base temporal.
- La KEK se respalda por separado y fuera de línea.

CI/CD (GitHub Actions): lint (ruff, eslint), tipos (mypy, tsc), pruebas, `pip-audit` y `npm audit`, escaneo de secretos (gitleaks), construcción de imágenes. Despliegue manual o por SSH al inicio.

Observabilidad: monitoreo de disponibilidad externo, rotación de logs (sin datos personales), alerta si falla el respaldo o el worker.

---

## 12. Plan por fases (paso a paso)

Orden: backend → frontend → endurecimiento. **Seguridad y devops base se resuelven en la Fase 0, antes de construir funciones.**

### Fase 0 — Cimientos (seguridad y devops primero)
1. ✅ Repo y estándares.
2. ✅ Docker Compose local (api, db). Sin Mailpit: Resend es por API.
3. ✅ **Módulo de cifrado**: `KeyProvider`, formato de valor, AAD, índice ciego, rotación. (Scripts de rotación por lotes sobre la base de datos: Fase 1.)
4. ✅ Base de datos: Alembic, `btree_gist`, tres roles de BD, plantilla de RLS, prueba de aislamiento entre clínicas (solo en CI).
5. 🔄 **EN CURSO** — Autenticación base: usuario, sesiones, argon2id, TOTP, invitaciones, límite de intentos, auditoría, `/health`. Hecho: migración 0002 y primitivas (`app/auth/`). Falta: bloques 3, 4 y 5 (ver sección 0.2).
6. CI con todas las comprobaciones de la sección 11 (ya existe un `ci.yml` mínimo; se amplía aquí).
7. Infra real: dominio en Cloudflare, VPS endurecido, Docker, Caddy, DNS y TLS, **despliegue del esqueleto** (`/health` + página vacía), respaldo cifrado **con restauración probada**, Resend verificado y correo de prueba entregado.

**Listo cuando:** el esqueleto responde por HTTPS en `{{DOMINIO}}`, un respaldo se restaura con éxito, un correo de Resend llega, y las pruebas de cifrado y aislamiento pasan en CI.

### Fase 1 — Backend núcleo
1. Modelos y migraciones del resto de la sección 7 (se elimina `_rls_demo`; `auditoria` y demás tablas con `clinica_id` reciben RLS).
2. Operador: crear clínica (genera su DEK), invitar admin, plan, estado, vigencia, suspender (bloquea login, conserva datos). Al activar la invitación se crea la membresía.
3. Membresías y RBAC con la matriz de la sección 6 como datos. Pruebas parametrizadas contra la matriz.
4. CRUD de médicos, asistentes y salas, con **límite de plan** (solo médicos activos) y aviso al acercarse al tope.
5. Pacientes cifrados, vínculo paciente-médico, visibilidad por rol, búsqueda (índice ciego + filtrado en memoria).
6. Agenda: crear, mover y cancelar citas; bloqueos; restricciones de exclusión; estados; comentarios.
7. Auditoría en toda mutación.
8. Scripts de rotación por lotes sobre la base de datos (reenvolver DEKs y recifrar).

**Listo cuando:** la matriz RBAC pasa completa; una prueba de acceso entre clínicas (IDOR) falla como debe; una prueba de concurrencia no permite doble reserva; y una inspección directa de la base de datos muestra solo texto cifrado en los campos marcados 🔒.

### Fase 2 — Recordatorios y correo
1. `ReminderChannel` + `WaMeLinkChannel`, normalización de teléfonos y validación de enlaces con números reales.
2. Plantilla por clínica con vista previa y validación.
3. Lista diaria de recordatorios con estados y respeto de `no_enviar_recordatorios`.
4. Tokens de confirmar/cancelar y endpoints públicos mínimos.
5. Jobs: resumen diario y alertas de citas sin confirmar (horario laboral, tope de frecuencia) con Resend; notificaciones en app.
6. Pruebas: token inválido o vencido, límites de intentos, correos sin datos personales, jobs idempotentes.

**Listo cuando:** un flujo completo (cita → recordatorio por enlace → confirmación → alerta si no confirma) funciona de punta a punta en el VPS.

### Fase 3 — Frontend
1. Base: Vite, TypeScript, rutas, cliente API tipado, CSP.
2. Login + 2FA + aceptación de términos + selector de clínica/perfil.
3. Calendario (día y semana, por médico y por sala), crear y editar cita con validación de disponibilidad, bloqueo de agenda.
4. Pacientes: lista, alta rápida, vincular a médicos.
5. Lista diaria de recordatorios con botones `wa.me`, estados y filtros.
6. Configuración de clínica: plantilla, política de cancelación, mapa, zona horaria, salas, personal.
7. Panel del operador en ruta separada.
8. Página pública de confirmar/cancelar, mínima y pensada para móvil.
9. Accesibilidad, uso en móvil, pruebas de extremo a extremo (Playwright) del flujo principal.

**Listo cuando:** una secretaria puede completar un día de trabajo (agendar, recordar, confirmar) sin ayuda, desde el teléfono y desde la computadora.

### Fase 4 — Endurecimiento y piloto
1. Revisión de seguridad (checklist OWASP ASVS selectivo, pruebas manuales de autorización, escaneo de dependencias, cabeceras, revisión de logs).
2. Simulacros de restauración y de rotación de claves.
3. Runbook de incidentes: qué hacer ante una brecha, cómo avisar a las clínicas con rapidez (la ley prevé informar vulneraciones significativas a los titulares).
4. Borradores legales (sección 14).
5. Alta de las 2 clínicas piloto. Medir inasistencias antes y después.
6. Retrospectiva y decidir el siguiente paso de producto (WhatsApp API, pagos, consentimiento).

---

## 13. Decisiones abiertas (con valor por defecto propuesto)

| Tema | Por defecto |
|---|---|
| Nombre y dominio | Pendiente (`{{APP_NAME}}`, `{{DOMINIO}}`); provisional `medi-clinic` / `localhost` |
| Proveedor de VPS | Pendiente |
| Almacenamiento de respaldos | Cloudflare R2 o Backblaze B2 |
| Horario del médico | Solo bloqueos puntuales dentro del horario de la clínica; horario semanal base como mejora posterior |
| Intervalo de alertas (n) | 4 horas, en horario laboral de la clínica |
| Retención y borrado de pacientes y citas | Borrado lógico y purga posterior configurable (plazo por definir) |
| Librería de calendario | Elegir tras revisar licencias |
| Validez del enlace de confirmación | Hasta el inicio de la cita |

---

## 14. Documentos legales a redactar (borradores, sin revisión de abogado)

1. **Términos y condiciones:** cláusula de encargo del tratamiento (la clínica es responsable de los datos de sus pacientes y encarga el tratamiento a la plataforma); la clínica declara que sus médicos están habilitados para ejercer; prohibición de datos médicos; borrado de datos sensibles detectados; indemnización; suspensión del servicio; límites de responsabilidad.
2. **Aviso de privacidad propio:** para los datos de admins, asistentes y médicos, de los que la plataforma sí es responsable.
3. **Texto modelo para el aviso de privacidad de cada clínica:** incluye los recordatorios de cita como finalidad (opcional, para que lo adapten).
4. Registro de aceptación (`aceptacion_legal`) al activar cada clínica, con versión y fecha.

---

## 15. Primer mensaje para iniciar

> Lee este documento completo, **empezando por la sección 0 (estado actual)**. Responde con: (1) tu resumen del proyecto y de dónde vamos, en máximo 8 líneas, (2) las dudas que **bloqueen** el bloque 3 del paso 0.5 (solo las bloqueantes) y el plan detallado de ese bloque en 5–10 líneas. **No escribas código todavía.** Si necesitas ver algún archivo existente para modificarlo, pídelo.

*(Primer mensaje original, para un proyecto desde cero: "Lee este documento completo. Responde con: resumen en máximo 10 líneas, dudas bloqueantes de la Fase 0 y plan detallado de los pasos 0.1 y 0.2. No escribas código todavía.")*