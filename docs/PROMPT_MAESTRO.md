# PROMPT MAESTRO — {{APP_NAME}}: agenda B2B para clínicas con recordatorios

> Pégalo al inicio de una sesión nueva y trabaja por fases. Nombre provisional: **medi-clinic**; dominio: `localhost` (ambos solo en `backend/app/config.py`).
> **Última actualización:** 2026-10-29. Continúa desde la sección 0.
> Para sesiones solo de backend existe `docs/PROMPT_BACKEND.md` (autocontenido). **Pendiente: actualizarlo con los cambios de WhatsApp de esta versión** (secciones 3, 5, 6, 7 y Fase 2).

---

## 0. Estado actual

**Fase 0 terminada, salvo el paso 0.7 (infra real), pospuesto hasta tener nombre, dominio y VPS. Siguiente: Fase 1, paso 1 (modelos y migraciones).**

Hecho: repo y estándares (0.1), Docker Compose local (0.2), módulo de cifrado (0.3), BD con RLS y roles (0.4), autenticación base (0.5: primitivas, throttle, auditoría, sesiones, CSRF, login en dos pasos, recuperación, activación de invitaciones, script del primer operador) y CI ampliado (0.6: ruff, pytest, mypy, `pip-audit`, gitleaks, Trivy, Dependabot). El CI está en verde.

**Orden acordado:** backend (Fases 1–2) y frontend (Fase 3) primero, todo probado en local con Docker; después el paso 0.7 y la Fase 4. El 0.7 se pospone, no se descarta.

**Cambio de rumbo (2026-10-29):** los recordatorios pasan a enviarse por la **API oficial de WhatsApp** desde un número único de la plataforma, con doble autorización del paciente (sección 7). El enlace `wa.me` queda como alternativa manual. Esto afecta las secciones 3, 5, 6, 7, 9 y 10; no afecta lo ya hecho en las Fases 0.

### 0.1 Pendiente
1. **Paso 0.5:** prueba de "sin datos personales en logs" para los endpoints de auth (la del script de bootstrap ya existe).
2. **Paso 0.7 (pospuesto):** infra real (ver sección 8). El criterio "listo cuando" de la Fase 0 sigue abierto hasta entonces: HTTPS en `{{DOMINIO}}`, respaldo restaurado y correo de Resend desde dominio propio.
3. **Fase 1, paso 1:** archivos que la IA debe pedir al propietario: `backend/alembic/versions/0001_*.py` (para ver `_rls_demo` y el montaje de RLS) y `backend/app/db/session.py`.
4. **Trámite con Meta (en paralelo; puede tardar días):** portafolio de negocio, verificación del negocio, número dedicado que no esté registrado en la app de WhatsApp, nombre visible aprobado y plantillas `optin_v1` y `recordatorio_v1` (sección 7.2). Conviene iniciarlo pronto: es necesario para la prueba real de la Fase 2.

### 0.2 Estructura del código existente
- `app/config.py` (Settings, prefijo `APP_`), `app/security.py` (cabeceras), `app/main.py` (routers).
- `app/crypto/`: `keys.py` (`KeyProvider`, `FileKeyProvider`), `envelope.py` (`wrap_dek`, `unwrap_dek`, `rewrap_dek`, `generate_dek`), `fields.py` (`FieldCipher`, `FieldContext`), `blind_index.py` (`blind_index`, `normalize_email`).
- `app/db/session.py`: `make_engine(rol)`, `clinic_session(engine, clinica_id)`.
- `app/auth/`: `passwords`, `totp`, `totp_replay` (`consumir_paso`), `recovery`, `tokens`, `throttle`, `audit` (`registrar`; rechaza claves de metadata con pinta de dato personal), `sessions`, `platform` (`PlatformCrypto`, `load_platform_crypto`).
- `app/api/`: `deps.py` (engine, KeyProvider, sesión de BD sin commit automático, IP, sesión, CSRF), `auth.py` (`/api/auth/login`, `/login/totp`, `/login/recuperacion`, `/logout`, `/me`), `activation.py` (`/api/auth/activar/iniciar` y `/confirmar`).
- `app/scripts/bootstrap_platform.py`: crea la DEK de plataforma y el primer operador (`crear_operador`).
- Migraciones: 0001 (base, `_rls_demo`), 0002 (auth), 0003 (`totp_ultimo_paso`).
- Pruebas: `tests/auth/`, `tests/db/`, `tests/api/` (con `conftest.py`: `client`, `engine`, `platform`, `crear_usuario`, `crear_invitacion`) y `tests/test_bootstrap.py`. Las que usan BD solo corren en CI.
- Infra: `infra/docker-compose.yml` (servicios `db`, `api`, y `migrate` y `bootstrap` con perfil `tools`), `infra/db/` (`init-roles.sh`, `roles.sql`), `infra/scripts/gen-local-secrets.sh`, `.github/workflows/ci.yml` (jobs `backend`, `secretos`, `imagen`) y `.github/dependabot.yml`.

### 0.3 Decisiones de implementación (prevalecen sobre el resto si chocan)
- **Stack:** Python 3.13, uv, FastAPI, SQLAlchemy 2 **async** + psycopg 3, Alembic (SQL explícito, `target_metadata = None`), argon2-cffi, pyotp. Dependencias nuevas con `uv add`. Cliente de pruebas: `starlette.testclient.TestClient` (paquete `httpx2` en dev). Ruff ignora `S101` y `S105` en `tests/`.
- **Flujo local:** `down -v` (solo si se regeneran secretos o roles) → `make up` → `make migrate` → `bootstrap` (`docker compose -f infra/docker-compose.yml --profile tools run --rm bootstrap`). Los roles de BD se crean solo cuando el volumen `pgdata` está vacío. `migrate` corre `alembic upgrade head` con el rol `migrador`; `bootstrap` también usa `migrador` (la API permanente nunca recibe ese secreto). Al repetir el bootstrap, borrar la entrada vieja del autenticador.
- **Pruebas de BD solo en CI:** `db` está en red interna. En local se saltan (`APP_TEST_DB != "1"`); el CI define `APP_TEST_DB=1` y `APP_DB_HOST=localhost`. Los `tests/db`, `tests/api` y `tests/test_bootstrap.py` deben salir *passed*, no *skipped*. Las pruebas deben limpiar solo sus propias filas (otras pruebas comparten la BD del CI).
- **Secretos como archivos** en `./secrets/` (carpeta 700, archivos **644 solo en desarrollo local**, porque Compose no cambia dueño ni modo al montarlos y el uid 10001 del contenedor debe leerlos; ignorados por git): `db_password`, `db_<rol>_password`, `kek_v1`… En el VPS se resuelve aparte (paso 0.7). Nunca en variables de entorno. Sin `.env.example`. **Nuevos (Fase 2):** `meta_access_token`, `meta_app_secret`, `meta_verify_token`.
- **Correo en desarrollo:** interfaz `EmailProvider` con implementación Resend por API HTTP. Sin dominio propio se usa el **remitente de pruebas de Resend** (`onboarding@resend.dev`), que solo entrega al correo del dueño de la cuenta; para probar entrega y rebote existen destinos de prueba de Resend (`delivered@resend.dev`, `bounced@resend.dev`; verificar en su documentación vigente). La API key va en `secrets/resend_api_key`. Las pruebas automatizadas usan un cliente simulado. Sin Mailpit. El envío desde dominio propio (SPF, DKIM, DMARC) se prueba en el paso 0.7.
- **WhatsApp (decidido 2026-10-29):**
  - **Un solo número de la plataforma** (sin Embedded Signup). Los costos de Meta los paga la plataforma; el cobro a las clínicas se define después (sección 10).
  - Canal principal `MetaCloudApiChannel` detrás de la interfaz `ReminderChannel`; `WaMeLinkChannel` queda como alternativa manual para pacientes sin opt-in aceptado.
  - **Orden del opt-in:** (1) la clínica atesta con una casilla por paciente; (2) la plataforma envía un primer mensaje neutro con botones Sí / No; (3) solo con `aceptado` se envían recordatorios automáticos. Detalle en la sección 7.
  - Cliente HTTP detrás de la interfaz `WhatsAppClient`: **simulado en pruebas**; en desarrollo, número de prueba de Meta. El webhook real necesita HTTPS público (paso 0.7 o un túnel temporal).
  - El webhook nunca guarda cuerpos de petición ni teléfonos en claro (sección 6).
- **Roles de BD:** `migrador` (dueño), `app` (CRUD sin ser dueño, para que RLS aplique), `operador` (sin permisos por defecto; se otorgan por tabla en migraciones). `auditoria` es de solo inserción para `app`; `llave_plataforma` de solo lectura para `app`.
- **Cifrado:** valores `BYTEA` con formato `formato(1)|versión_dek(4)|nonce(12)|cifrado+tag`; AAD `tabla|columna|clinica_id|fila_id` (`plataforma` si no hay clínica). DEK envuelta con AAD `clinica|<uuid>|v<n>` o `plataforma|v<n>`. Índice ciego: HMAC-SHA256 con clave HKDF de la DEK y la columna. Contextos de cifrado en auth: `ctx("email", id)`, `ctx("totp_secret", id)`, y `tabla="invitacion"` para invitaciones.
- **Sesiones:** 8 h de inactividad, 24 h absolutas; sesión intermedia (`mfa_ok=false`) de 10 min. Cookie `HttpOnly; Secure; SameSite=Lax`, con prefijo `__Host-` fuera de local. **CSRF:** HMAC del token de sesión (clave HKDF de la KEK, nada se guarda), cookie legible por JS y cabecera `X-CSRF-Token` en operaciones con sesión; login y activación están exentos.
- **Login:** credenciales malas → 401 uniforme (con `verify_dummy` si la cuenta no existe); límite superado → 429 genérico. El operador sin TOTP no entra. Nueva sesión al subir de nivel.
- **Límite de intentos (en BD, solo fallos, HMAC de la clave con HKDF de la KEK):** cuenta 5 en 5 min; IP 20 en 20 min; activación por IP 10 en 15 min y por invitación 5 en 15 min. Un login exitoso limpia los fallos de la cuenta, **no** los de la IP. Sin IP determinable solo se limita por cuenta. Los fallos se commitean antes de responder el error.
- **IP real:** cabecera configurable `APP_IP_HEADER` (en producción `CF-Connecting-IP`, y el origen solo debe aceptar IPs de Cloudflare). Se define en el paso 0.7.
- **Activación en dos pasos:** `/iniciar` (valida invitación, fija contraseña, crea usuario con `activo=false` y devuelve secreto TOTP; reintentable) y `/confirmar` (verifica TOTP, consume la invitación, activa, crea sesión y devuelve 10 códigos de recuperación una sola vez). Si el email ya tiene cuenta activa, responde el 400 genérico; las invitaciones a usuarios existentes llegan en la Fase 1.
- **TOTP:** 6 dígitos, 30 s, ±1 paso, sin reutilizar (`usuario.totp_ultimo_paso`). Recuperación: 10 códigos de un solo uso, solo hash.
- **Bootstrap del operador:** pide email y contraseña, muestra el secreto TOTP y exige un código válido antes de escribir; crea la DEK de plataforma, el usuario (`es_operador`, TOTP activo) y 10 códigos de recuperación, todo en una transacción; falla si `llave_plataforma` ya tiene filas.
- **Rotación de KEK:** invalida las claves derivadas (contadores de intentos y CSRF); los usuarios deben volver a entrar. Va al runbook.
- **Imagen Docker:** `python:3.13-slim` sin `pip` del sistema (quitado en el Dockerfile para no arrastrar sus paquetes embebidos), `uv sync --no-cache`, usuario 10001, sistema de archivos de solo lectura.
- **CI:** job `backend` (Postgres 16, secretos locales, roles, migraciones, `make check`, `pip-audit` sobre dependencias de producción), job `secretos` (gitleaks con historial completo, vía Docker) y job `imagen` (build + Trivy vía Docker, falla con HIGH/CRITICAL que tengan parche). Dependabot semanal para uv, Docker y GitHub Actions. Frontend (`eslint`, `tsc`, `npm audit`) se añade en la Fase 3.
- `invitacion` guarda `email` cifrado; `invitacion.clinica_id` sin FK hasta la Fase 1. La **membresía** se crea en la Fase 1. `auditoria` sin RLS hasta la Fase 1. `_rls_demo` se elimina en la Fase 1.
- Docs de la API (`/docs`) solo con `APP_ENTORNO=local`. Entorno del propietario: Ubuntu, repo en `~/Documents/personal/medi-clinic`, puerto 8000 libre.
- **Pendiente para el worker:** purgar sesiones vencidas y llamar a `throttle.purgar_antiguos`; (Fase 2) enviar recordatorios, alertas de citas sin confirmar y resumen diario. Scripts de rotación por lotes sobre la BD: Fase 1.

### 0.4 Convenciones de trabajo con el propietario
- Comandos con `make`: `help`, `check` (ruff + pytest + mypy), `format`, `up`, `down`, `migrate`. Lo de una sola vez va en el README.
- **La IA no ejecuta código ni ve el repo.** Entrega **solo los archivos creados o modificados, uno por uno**, con su ruta, e indica los comandos (`make format && make check`, commit, push). Si necesita ver un archivo existente, lo pide. Si ruff, mypy o el CI fallan, el propietario pega el error.
- Cada paso o bloque se confirma con `make check` y el CI en verde.
- Prefiere explicaciones muy cortas y no domina terminología de seguridad: explicar conceptos nuevos en pocas líneas (KEK = llave maestra fuera de la BD; DEK = llave de datos por clínica; AAD = etiqueta que ata el dato a su fila; índice ciego = huella para buscar sin descifrar; RLS = la BD filtra filas por clínica).
- **Todo lo que el propietario tenga que saber para operar el proyecto (flujos, comandos, orden de pasos) debe quedar escrito en este documento o en el README**, no solo en la conversación.

---

## 1. Reglas de trabajo (para la IA)

1. Responde en español, conciso.
2. **Antes de crear o modificar código, pide el contexto que falte** y confirma el plan en 5–10 líneas.
3. Una fase y un paso a la vez. Al terminar: qué cambió, cómo probarlo y siguiente paso.
4. **Nunca** guardes, registres en logs, pongas en URLs ni muestres datos personales en claro. Sin datos reales en pruebas.
5. Si algo choca con este documento, avisa; no cambies decisiones en silencio.
6. Nada fuera de alcance (sección 3) ni dependencias nuevas sin justificarlas en una línea.
7. Todo modular con interfaces: canal de recordatorios, cliente de WhatsApp, proveedor de claves, proveedor de correo, pagos.
8. Pruebas junto con el código, sobre todo de autorización, aislamiento entre clínicas y cifrado.
9. Los textos legales son borradores sin revisión de abogado; márcalos así.

---

## 2. Producto y glosario

Aplicación web **B2B** para clínicas y consultorios pequeños de México (empezando por dentistas) que llevan citas en Excel o papel.
- Agenda por médico (y sala, opcional) con roles.
- Recordatorios por **WhatsApp con la API oficial de Meta**, desde un número único de la plataforma, solo a pacientes con autorización aceptada (sección 7). La confirmación y la cancelación se hacen con botones dentro del mismo chat y actualizan la cita automáticamente.
- Alternativa manual: enlace `wa.me` desde el WhatsApp de la clínica, para pacientes sin autorización aceptada.
- Resumen diario y alertas de citas sin confirmar por correo (sin datos de pacientes).
- Alta **manual** de clínicas por el operador. Seguridad de datos de pacientes como prioridad. Sin historial médico ni documentos.
- Piloto: 2 consultorios gratis. Futuro: suscripción por rango de médicos y cobro de los mensajes de WhatsApp (por definir).

| Término | Significado |
|---|---|
| Clínica | Tenant (puede ser un solo médico). |
| Sala | Cuarto de consulta, opcional. |
| Usuario | Identidad de login global. |
| Membresía | Usuario + clínica + rol + perfil; un usuario puede tener varias. |
| Admin / Asistente / Médico | Roles de clínica. Un admin por clínica; solo los médicos cuentan para el plan. |
| Paciente | Registro dentro de una clínica; sin login; nunca se comparte entre clínicas. |
| Cita / Bloqueo | Eventos de agenda de un médico. |
| Operador | Dueño de la plataforma; rol global aparte. |
| Opt-in | Autorización del paciente para recibir recordatorios por WhatsApp (casilla de la clínica + respuesta Sí del paciente). |
| Baja | El paciente pidió no recibir más mensajes; vale para todo el número de la plataforma, en todas las clínicas. |

---

## 3. Decisiones cerradas y fuera de alcance

- **Frontend:** React + TypeScript (Vite), mismo origen que la API (Caddy enruta `/api`). **Hosting:** VPS único, Docker Compose, Caddy. **DNS/dominio:** Cloudflare. **Correo:** Resend, sin datos de pacientes.
- **Autorización de recordatorios (opt-in) en dos pasos:** (1) la clínica atesta por paciente con una casilla (quién y cuándo quedan registrados); (2) el paciente responde **Sí** a un primer mensaje neutro por WhatsApp. Los términos y condiciones hacen a la clínica responsable de todos los datos de sus pacientes, de la autorización explícita de los recordatorios y de la exactitud de los teléfonos. Es menos sólido que una firma por escrito y **no tiene validación legal** (decisión del propietario).
- **Teléfonos:** quien da de alta o cambia un paciente debe **confirmar el teléfono** (sección 7.1).
- **Cédula:** no la verifica la plataforma. **Planes:** 5, 10, 20, 50 médicos; más, contacto. **Suscripción:** manual y gratuita al inicio, con campos de plan, estado y vigencia desde el día 1.
- **Datos de salud prohibidos** (comentarios de cita: máx. 500 caracteres, con aviso). El **operador no ve datos de pacientes** (ni por aplicación ni por permisos de BD).
- **Fuera del MVP:** pagos y cobro automático, archivos, expediente clínico, registro público, portal para pacientes, marketplace, sincronización con calendarios externos, app nativa, analítica de terceros, **control automático de la calidad del número de WhatsApp** (se revisa a mano en WhatsApp Manager) y **enlace público de confirmación/cancelación** (pospuesto: la confirmación pasa por botones de WhatsApp). Dejar el camino listo para pagos y cobro de mensajes.

---

## 4. Roles y permisos

| Acción | Operador | Admin | Asistente | Médico |
|---|---|---|---|---|
| Crear clínica, invitar admin, plan/estado/vigencia, suspender | sí | no | no | no |
| Ver pacientes y citas | **no** | todos | todos | solo los suyos |
| Crear/editar/cancelar citas | no | sí | sí | las suyas |
| Bloquear agenda | no | cualquier médico | cualquier médico | la suya |
| Agregar pacientes (confirmando el teléfono) | no | sí | sí | sí |
| Marcar la autorización de recordatorios | no | sí | sí | sus pacientes |
| Reactivar recordatorios tras baja o rechazo (a petición del paciente en la clínica) | no | sí | sí | sus pacientes |
| Vincular pacientes a otros médicos | no | sí | sí | no |
| Agregar médicos | no | sí | sí | no |
| Agregar asistentes | no | sí | no | no |
| Crear/editar salas | no | sí | no | no |
| Configurar clínica (texto manual, política, mapa) | no | sí | no | no |
| Borrar (pacientes, citas, personal) | no | sí | no | no |

La matriz vive **como datos** en un solo módulo de autorización y las pruebas se parametrizan contra ella. Un médico solo ve pacientes vinculados a él. Un usuario con varias membresías elige contexto al entrar.

---

## 5. Modelo de datos pendiente (UUID; 🔒 = cifrado)

Ya existen (migraciones 0002–0003): `usuario` (con `es_operador`, `totp_activo`, `totp_ultimo_paso`), `codigo_recuperacion`, `sesion`, `invitacion`, `intento_login`, `auditoria`, `llave_plataforma`. Falta (Fase 1 y 2), todas con `clinica_id` y RLS salvo que se indique:

- **clinica**: id, nombre, zona_horaria (IANA, por defecto `America/Mexico_City`), plan (`p5|p10|p20|p50|custom`), estado (`prueba|activa|suspendida`), vigencia_hasta, google_maps_url, politica_cancelacion, plantilla_recordatorio (texto del **canal manual** `wa.me`), horario_laboral, dek_wrapped, dek_version, creado_en.
- **membresia**: usuario_id, clinica_id, rol, nombre 🔒, contacto_preferido 🔒 (opcional, médicos), activo. Único (usuario, clínica); **índice único parcial: un admin activo por clínica**.
- **sala**: id, clinica_id, nombre, activa.
- **paciente**: nombre 🔒, telefono 🔒 (E.164), telefono_idx, **telefono_confirmado_por** (membresía), **telefono_confirmado_en**, no_enviar_recordatorios, **optin_estado** (`sin_solicitar|pendiente|aceptado|rechazado`; por defecto `sin_solicitar`), **optin_atestado_por** (membresía), **optin_atestado_en**, **optin_solicitado_en**, **optin_respondido_en**, **optin_plantilla_version**, creado_por, eliminado_en. La **baja no vive aquí**: es global (ver `baja_whatsapp`). **Cambiar el teléfono exige confirmarlo de nuevo y reinicia el opt-in a `sin_solicitar`.**
- **baja_whatsapp** (global a la plataforma, **sin `clinica_id` ni RLS por clínica**, solo hash): id, telefono_idx (índice ciego con clave de **plataforma**, no por clínica), creada_en, reactivada_en (nulo), reactivada_por_membresia (nulo). Índice único parcial sobre `telefono_idx` donde `reactivada_en` es nulo. Antes de cada envío se consulta esta tabla; el estado de baja de un paciente se calcula al leer, sin tocar sus filas.
- **mensaje_whatsapp**: id, clinica_id, paciente_id, evento_id (nulo en opt-in), tipo (`optin|recordatorio`), plantilla_version, wa_message_id (único), estado (`enviado|entregado|leido|fallido`), categoria (la reporta Meta), error_codigo (sin datos personales), creado_en, actualizado_en. Único por (`evento_id`, `tipo`) en recordatorios, para no duplicar envíos. Sirve también para **medir consumo por clínica y mes**.
- **webhook_evento** (sin RLS): clave_unica (id de mensaje o de estado entrante + tipo), recibido_en. **Sin cuerpo ni teléfonos.** Da idempotencia al webhook.
- **evento_agenda** (cita y bloqueo): tipo, medico_membresia_id, sala_id (nulo), paciente_id (nulo en bloqueos), rango (`tstzrange`), estado (`pendiente_envio|enviado|confirmada|cancelada`), comentario 🔒 (≤500), cancelada_por (`paciente|personal`), enviado_en, confirmado_en, creado_por, creado_en, actualizado_en. Exclusión (`btree_gist`) sobre `(medico, rango)` con estado ≠ cancelada, y otra sobre `(sala_id, rango)` para citas con sala. Si el envío de un recordatorio falla, la cita vuelve a `pendiente_envio` y se notifica al personal.
- **token_cita** *(opcional, pospuesto con el enlace público)*: evento_id, token_hash (SHA-256), expira_en.
- **notificacion**: destinatario_membresia_id, tipo (`sin_confirmar|envio_fallido|cancelada_por_paciente|baja`), evento_id, creada_en, leida_en. Sin datos personales.
- **aceptacion_legal**: clinica_id, usuario_id, documento (`terminos|aviso`), version, aceptado_en, ip.

La auditoría ya existente registra quién atestó, confirmó el teléfono o reactivó, y cuándo (sin datos personales en la metadata).

---

## 6. Seguridad (no negociable)

- **Cifrado de campos** en el backend: KEK (fuera de la BD, de respaldos y del repo; se respalda aparte y fuera de línea; perderla = perder los datos) → DEK por clínica y de plataforma → índice ciego. AES-256-GCM. Búsqueda por nombre: descifrar en memoria la lista del médico y filtrar; sin `LIKE` sobre campos cifrados. Límite honesto a documentar: si comprometen el servidor en ejecución, pueden descifrar.
- **Autenticación:** argon2id (12–128 caracteres); **TOTP obligatorio** para admin y operador, opcional para los demás; invitaciones de un solo uso (72 h); recuperación de contraseña sin revelar si la cuenta existe (pendiente).
- **Autorización:** una sola capa centralizada; cada consulta filtra por `clinica_id`; RLS como segunda barrera (`app.clinica_id` por transacción). 404 uniforme para recursos ajenos; IDs no secuenciales.
- **Privacidad:** logs sin cuerpos de petición ni datos personales (redactar teléfonos, nombres, correos). Sin scripts de terceros, sin analítica, sin datos personales en `localStorage`/`sessionStorage`/URLs. Cabeceras: CSP estricta, HSTS, `X-Content-Type-Options`, `Referrer-Policy`, `frame-ancestors 'none'`.
- **Webhook de WhatsApp:**
  - Verificación inicial con `meta_verify_token`; cada POST se valida con la firma `X-Hub-Signature-256` (HMAC con `meta_app_secret`, comparación en tiempo constante). Sin firma válida, se rechaza.
  - Límite de tamaño y de peticiones; responder 200 rápido y de forma idempotente (`webhook_evento`).
  - Los teléfonos que llegan en el webhook son datos personales: se calcula el índice ciego y se descartan. Nunca en logs ni almacenados en claro.
  - Una respuesta con botón lleva `accion:evento_id`. **Antes de actuar, validar que el teléfono remitente corresponde al paciente de esa cita.** Se ignora el texto libre y las respuestas a citas pasadas o canceladas.
- **Antes de cada envío por API** comprobar: `optin_estado = aceptado`, sin baja global activa, `no_enviar_recordatorios` falso, clínica activa y cita no cancelada. Cada mensaje incluye la opción "Dejar de recibir".
- **Enlace público de confirmar/cancelar** *(opcional, pospuesto)*: si se implementa, token de ≥256 bits guardado solo como hash, con vencimiento, sin nombre ni teléfono del paciente en la página, respuesta idéntica para token inválido o vencido, límite de intentos y acciones idempotentes.
- **CI:** ruff, mypy, pruebas, `pip-audit`, gitleaks y Trivy ya activos; `eslint`, `tsc` y `npm audit` se añaden con el frontend (Fase 3).

---

## 7. Recordatorios y correo

### 7.1 Autorización del paciente (opt-in)
1. **Alta del paciente.** La API exige `telefono_confirmado = true` (quien da de alta revisa el número y lo confirma; en la UI, mostrar el número en grande y pedir que se lea de vuelta al paciente). Sin esa confirmación, el alta falla. Cambiar el teléfono repite la confirmación y reinicia el opt-in.
2. **Casilla de la clínica:** "El paciente autorizó recibir recordatorios por WhatsApp". Al marcarla se guardan `optin_atestado_por` y `optin_atestado_en` y se registra en auditoría. **Sin casilla no se envía nada por API.**
3. **Primer mensaje (plantilla `optin_v1`, un solo intento):** neutro, **sin nombre del paciente ni fecha**, con botones Sí / No. `optin_estado` pasa a `pendiente`.
4. **Respuesta:** Sí → `aceptado`; No → `rechazado`. Sin respuesta, el paciente sigue `pendiente`: **no recibe recordatorios automáticos y no se insiste.** Si responde dentro de la ventana de 24 h, se puede enviar un acuse breve sin plantilla.
5. **Baja:** el botón "Dejar de recibir" de cualquier mensaje crea una fila en `baja_whatsapp` y bloquea el envío para ese teléfono en **todas** las clínicas. El sistema **nunca** la revierte solo.
6. **Reactivación:** solo si el paciente lo pide en la clínica. Personal autorizado (sección 4) marca `reactivada_en` en `baja_whatsapp` (auditado), vuelve a marcar la casilla y el sistema repite el paso 3 (se vuelve a pedir el Sí).

### 7.2 Plantillas de la plataforma (aprobadas por Meta, versionadas)
- `optin_v1`: "{{APP_NAME}}: ¿aceptas recibir notificaciones de tus citas por WhatsApp de parte de {clínica} y {médico}? Puedes dejar de recibirlas cuando quieras." Botones: **Sí · No**.
- `recordatorio_v1`: recordatorio de consulta con `{paciente}`, `{medico}`, `{clinica}`, `{fecha}`, `{hora}`, `{sala}`, `{politica_cancelacion}`, `{contacto_medico}` (opcional) y `{enlace_mapa}`. Botones: **Confirmar · Cancelar · Dejar de recibir**.
- **La estructura es fija:** las clínicas solo personalizan el *valor* de las variables (política de cancelación, contacto del médico, mapa). Cambiar el texto de una plantilla exige una versión nueva y una aprobación nueva de Meta.
- Tono transaccional; **sin tipo de tratamiento ni datos clínicos**. Verificar que Meta mantenga ambas plantillas como *utility* (si las reclasifica como marketing, el costo sube) y revisar los límites vigentes de longitud de variables y de botones.

### 7.3 Envío automático
- Job del worker, idempotente: para citas en `pendiente_envio` con paciente `aceptado`, envía `recordatorio_v1` el **día anterior a una hora configurable** (por defecto 10:00, hora de la clínica); las citas creadas después de esa hora se envían de inmediato si faltan más de 2 horas (sección 10).
- Al aceptarlo Meta, la cita pasa a `enviado`. Si el mensaje falla (`fallido`), vuelve a `pendiente_envio` y se notifica al personal (`envio_fallido`) para gestión manual.
- **Botón Confirmar** → `confirmada` (`confirmado_en`). **Botón Cancelar** → `cancelada` (`cancelada_por = paciente`), libera el espacio y avisa al personal.
- Citas `enviado` sin confirmar: alerta a asistentes y admin cada **4 h** (configurable), solo en horario laboral y con tope de frecuencia (notificación en app y correo sin datos de pacientes).
- El número de la plataforma no se usa para conversar: el texto libre del paciente se ignora.

### 7.4 Alternativa manual (`wa.me`)
Lista diaria con botón por paciente para quienes **no** tienen opt-in aceptado. Excluye a quienes están en `rechazado`, con baja global o con `no_enviar_recordatorios`. Usa el texto libre `plantilla_recordatorio` de la clínica, **sin enlace de confirmación**; la asistente actualiza el estado a mano. Enlace `https://wa.me/52XXXXXXXXXX?text=<mensaje codificado>`; validar el formato con números reales de prueba (y el formato del número en la API de Meta: `52…` frente a `521…`).

### 7.5 Costos y calidad del número
- La plataforma paga a Meta. `mensaje_whatsapp` mide el consumo por clínica y mes. Cobro por definir (sección 10).
- La calidad del número depende de los bloqueos y reportes de los últimos días, así que un número compartido es sensible a los teléfonos equivocados. **No es prioridad automatizarlo:** se revisa a mano en WhatsApp Manager (calificación, límites). Mejoras futuras: tope diario de opt-ins, aumento gradual, aviso por webhook, pausa automática y métricas de "No" y bajas por clínica.

### 7.6 Correo con Resend
En desarrollo, API con remitente de pruebas (ver 0.3). Con dominio propio (paso 0.7): SPF, DKIM y DMARC (`p=none` → `quarantine`), registros en Cloudflare como solo DNS. Los correos llevan **solo conteos y un enlace al panel**. Prueba (snapshot) de que ningún correo incluye nombres ni teléfonos.

---

## 8. Arquitectura y DevOps

- Repo: `/backend` (FastAPI), `/frontend` (React), `/infra` (compose, `db/` roles, Caddyfile, respaldos), `/docs`, `/.github`. Contenedores: `api`, `worker` (recordatorios, alertas, resumen diario, purgas), `db` (solo red interna), `caddy`.
- Tipos del frontend generados desde OpenAPI. Calendario: licencia compatible (las vistas por recurso de FullCalendar son premium; evaluar react-big-calendar). Hora en UTC (`timestamptz`), mostrada en la zona de la clínica; citas de mínimo 15 min.
- **VPS (paso 0.7, pospuesto):** usuario sin privilegios, SSH solo con llaves sin root, firewall (80/443 y 22 limitado), `fail2ban`, actualizaciones automáticas, contenedores sin root, secretos fuera del repo (resolver permisos de archivos de secretos para el contenedor). Cloudflare con proxy y SSL Full (strict), límites de peticiones en login, `APP_IP_HEADER=CF-Connecting-IP` y origen limitado a IPs de Cloudflare. **La ruta del webhook de Meta debe quedar accesible para Meta** (revisar reglas de WAF y límites de Cloudflare).
- **Respaldos (0.7):** `pg_dump` nocturno cifrado con `age` (llave privada fuera de línea), subido fuera del VPS (R2 o B2, por decidir); retención 7 diarios, 4 semanales, 6 mensuales; **restauración probada cada mes**; KEK respaldada aparte.
- Observabilidad: monitoreo externo de disponibilidad, rotación de logs sin datos personales, alerta si falla el respaldo o el worker.

---

## 9. Plan por fases

### Fase 0 — Cimientos (terminada salvo 0.7)
- 0.1–0.6 hechos (ver sección 0).
- **0.7 Infra real (pospuesto):** dominio, VPS endurecido, Docker, Caddy, TLS, esqueleto desplegado (`/health` + página vacía), respaldo con restauración probada, Resend verificado con dominio propio y correo de prueba entregado. Sub-pasos previstos: 0.7a endurecer VPS, 0.7b Docker + Caddy + Cloudflare, 0.7c desplegar esqueleto, 0.7d respaldos con `age`, 0.7e Resend con dominio, **0.7f webhook de Meta en HTTPS (URL y token de verificación) y número real**.
- **Listo cuando:** el esqueleto responde por HTTPS en `{{DOMINIO}}`, un respaldo se restaura, un correo de Resend llega, y las pruebas de cifrado y aislamiento pasan en CI.

### Fase 1 — Backend núcleo (siguiente)
1. Modelos y migraciones de la sección 5, **incluidos los campos de opt-in de `paciente` y la tabla `baja_whatsapp`** (se elimina `_rls_demo`; RLS en `auditoria` para eventos con `clinica_id`; FK de `invitacion.clinica_id`). `mensaje_whatsapp` y `webhook_evento` pueden crearse aquí o al inicio de la Fase 2.
2. Operador: crear clínica (genera su DEK), invitar admin, plan, estado, vigencia, suspender (bloquea login, conserva datos). Al activar la invitación se crea la membresía; invitaciones a usuarios existentes.
3. Membresías y RBAC con la matriz como datos, pruebas parametrizadas.
4. CRUD de médicos, asistentes y salas con **límite de plan** (solo médicos activos) y aviso al acercarse al tope.
5. Pacientes cifrados, **confirmación obligatoria del teléfono** (el cambio de teléfono la repite y reinicia el opt-in), casilla de autorización, reactivación tras baja, vínculo paciente-médico, visibilidad por rol, búsqueda.
6. Agenda: crear, mover y cancelar citas, bloqueos, exclusiones, estados, comentarios.
7. Auditoría en toda mutación. 8. Scripts de rotación por lotes (reenvolver DEKs, recifrar). 9. Recuperación de contraseña (con `EmailProvider` de Resend en modo de pruebas).
- **Listo cuando:** la matriz RBAC pasa completa; una prueba IDOR entre clínicas falla como debe; una prueba de concurrencia no permite doble reserva; crear o cambiar un paciente sin confirmar el teléfono falla; y la BD muestra solo texto cifrado en los campos 🔒.

### Fase 2 — WhatsApp, recordatorios y correo
1. Interfaces `ReminderChannel` y `WhatsAppClient`; `MetaCloudApiChannel` (con cliente simulado en pruebas) y `WaMeLinkChannel`; normalización E.164 y validación del formato con un número de prueba de Meta.
2. Opt-in: casilla por paciente en la API, envío de `optin_v1` (un solo intento), estados y comprobaciones previas al envío (sección 6).
3. Webhook: verificación, firma, idempotencia, estados de entrega, respuestas con botones (validando el teléfono remitente), baja global, acuses breves.
4. Recordatorios automáticos (job idempotente, `recordatorio_v1`), transiciones de estado, fallos, alertas de citas sin confirmar y resumen diario con Resend (remitente de pruebas en local); notificaciones en app.
5. Lista manual `wa.me` para pacientes sin opt-in aceptado.
6. Medición de consumo por clínica y mes.
7. Pruebas: firma inválida; respuestas repetidas (idempotencia); teléfono remitente distinto del paciente; una baja bloquea envíos en todas las clínicas; la reactivación solo por personal autorizado; sin casilla no se envía el opt-in; sin `aceptado` no se envía el recordatorio; correos sin datos personales; el webhook no deja teléfonos en logs.
- **Listo cuando:** el flujo completo funciona en local con el cliente simulado: paciente con casilla → opt-in Sí → recordatorio → botón Confirmar actualiza la cita → sin respuesta genera alerta; una baja bloquea los envíos. La **prueba real con el número de prueba de Meta** se hace cuando exista un túnel temporal o el paso 0.7.

### Fase 3 — Frontend
Vite + TypeScript + CSP; login, 2FA, términos y selector de clínica; calendario (día/semana, por médico y sala) con alta, edición y bloqueos; pacientes (**confirmación del teléfono al crear o cambiar, casilla de autorización, estado de opt-in visible y reactivación tras baja**); lista manual de recordatorios con botones `wa.me`; bandeja de notificaciones (envíos fallidos, citas sin confirmar, cancelaciones, bajas); configuración de clínica; panel del operador en ruta separada; accesibilidad y pruebas E2E (Playwright). CI: `eslint`, `tsc`, `npm audit`. *(La página pública de confirmar/cancelar queda pospuesta.)*
- **Listo cuando:** una secretaria completa un día de trabajo (agendar, registrar pacientes, ver confirmaciones) sin ayuda, desde teléfono y computadora, en local.

### Fase 4 — Endurecimiento y piloto
Completar el 0.7 si sigue pendiente. Prueba real de WhatsApp con el número de la plataforma. Revisión de seguridad (OWASP ASVS selectivo), simulacros de restauración y rotación de claves, runbook de incidentes (la ley prevé avisar vulneraciones significativas a los titulares), borradores legales (términos con encargo de tratamiento y **cláusulas de autorización explícita de recordatorios, exactitud de teléfonos y suspensión del envío por abuso**; aviso de privacidad propio; texto modelo de aviso para cada clínica; registro en `aceptacion_legal`), alta de las 2 clínicas piloto midiendo inasistencias y la calificación del número en WhatsApp Manager, y retrospectiva.

---

## 10. Decisiones abiertas

| Tema | Por defecto |
|---|---|
| Nombre y dominio | Pendiente; provisional `medi-clinic` / `localhost` |
| VPS | Pendiente (recomendado: 2 vCPU / 4 GB, Ubuntu 24.04 LTS) |
| Almacenamiento de respaldos | Cloudflare R2 o Backblaze B2 |
| Número y nombre visible de WhatsApp | Pendiente: número dedicado y nombre aprobado por Meta |
| Cobro de mensajes de WhatsApp | Propuesta: costo de Meta + 30%, o paquete incluido; la medición ya está prevista |
| Hora de envío automático | Día anterior a las 10:00 (hora de la clínica), configurable; citas creadas tarde: inmediato si faltan más de 2 h |
| Calidad del número | Revisión manual en WhatsApp Manager; automatización después |
| Enlace público de confirmación | Pospuesto |
| Horario del médico | Bloqueos puntuales dentro del horario de la clínica |
| Retención de pacientes y citas | Borrado lógico y purga configurable (plazo por definir) |
| Librería de calendario | Elegir tras revisar licencias |

---

## 11. Primer mensaje para iniciar

> Lee este documento completo, **empezando por la sección 0**. Responde con: (1) resumen del proyecto y de dónde vamos en máximo 8 líneas, (2) las dudas que **bloqueen** el paso 1 de la Fase 1 (solo las bloqueantes) y el plan de ese paso en 5–10 líneas. **No escribas código todavía.** Pídeme los archivos que necesites ver.