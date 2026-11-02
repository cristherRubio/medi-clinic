"""Modelo de clínica: clinica, personal, sala, paciente, agenda, notificación y aceptación legal.

Elimina `_rls_demo`, activa RLS en `auditoria` y crea `clinicas_de_usuario` para el login.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONTEXTO = "nullif(current_setting('app.clinica_id', true), '')::uuid"
# Columna estándar de las tablas de clínica: toma el contexto por defecto.
CID = f"clinica_id uuid NOT NULL DEFAULT {CONTEXTO} REFERENCES clinica(id)"

TABLAS_CLINICA = (
    "personal",
    "sala",
    "paciente",
    "paciente_medico",
    "evento_agenda",
    "notificacion",
    "aceptacion_legal",
)


def _aislar(tabla: str) -> None:
    op.execute(f"ALTER TABLE {tabla} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {tabla} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY aislamiento_clinica ON {tabla} TO app
            USING (clinica_id = {CONTEXTO})
            WITH CHECK (clinica_id = {CONTEXTO})
        """
    )


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS _rls_demo")

    # --- clinica ---------------------------------------------------------------------
    # rfc, representante_nombre y representante_curp van cifrados (DEK de la clínica).
    # Persona física: el representante es el mismo titular.
    op.execute(
        """
        CREATE TABLE clinica (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            nombre text NOT NULL,
            tipo_persona text NOT NULL CHECK (tipo_persona IN ('fisica', 'moral')),
            nombre_legal text NOT NULL,
            rfc bytea NOT NULL,
            representante_nombre bytea NOT NULL,
            representante_curp bytea NOT NULL,
            zona_horaria text NOT NULL DEFAULT 'America/Mexico_City',
            plan text NOT NULL DEFAULT 'p5'
                CHECK (plan IN ('p5', 'p10', 'p20', 'p50', 'custom')),
            estado text NOT NULL DEFAULT 'prueba'
                CHECK (estado IN ('prueba', 'activa', 'suspendida')),
            vigencia_hasta date,
            notificaciones_whatsapp boolean NOT NULL DEFAULT false,
            google_maps_url text,
            politica_cancelacion text,
            plantilla_recordatorio text,
            horario_laboral jsonb NOT NULL DEFAULT '{}',
            dek_wrapped bytea NOT NULL,
            dek_version int NOT NULL DEFAULT 1,
            creado_en timestamptz NOT NULL DEFAULT now()
        )
        """
    )

    # --- personal (admin, asistente, médico) -----------------------------------------
    op.execute(
        f"""
        CREATE TABLE personal (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            {CID},
            usuario_id uuid NOT NULL REFERENCES usuario(id),
            rol text NOT NULL CHECK (rol IN ('admin', 'asistente', 'medico')),
            nombre bytea NOT NULL,
            contacto_preferido bytea,
            activo boolean NOT NULL DEFAULT true,
            creado_en timestamptz NOT NULL DEFAULT now(),
            UNIQUE (clinica_id, id),
            UNIQUE (clinica_id, usuario_id)
        )
        """
    )
    # Un solo admin activo por clínica.
    op.execute(
        "CREATE UNIQUE INDEX personal_un_admin ON personal (clinica_id) "
        "WHERE rol = 'admin' AND activo"
    )
    op.execute("CREATE INDEX ON personal (usuario_id)")

    # --- sala --------------------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE sala (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            {CID},
            nombre text NOT NULL,
            activa boolean NOT NULL DEFAULT true,
            UNIQUE (clinica_id, id)
        )
        """
    )

    # --- paciente ----------------------------------------------------------------------
    # telefono_idx: índice ciego con la clave de PLATAFORMA (sirve para duplicados,
    # webhook y baja global). Sin unicidad: un teléfono puede ser de varios familiares.
    op.execute(
        f"""
        CREATE TABLE paciente (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            {CID},
            nombre bytea NOT NULL,
            telefono bytea NOT NULL,
            telefono_idx bytea NOT NULL,
            telefono_confirmado_por uuid NOT NULL,
            telefono_confirmado_en timestamptz NOT NULL,
            no_enviar_recordatorios boolean NOT NULL DEFAULT false,
            optin_estado text NOT NULL DEFAULT 'sin_solicitar'
                CHECK (optin_estado IN ('sin_solicitar', 'pendiente', 'aceptado', 'rechazado')),
            optin_atestado_por uuid,
            optin_atestado_en timestamptz,
            optin_solicitado_en timestamptz,
            optin_respondido_en timestamptz,
            optin_plantilla_version text,
            creado_por uuid NOT NULL,
            creado_en timestamptz NOT NULL DEFAULT now(),
            eliminado_en timestamptz,
            UNIQUE (clinica_id, id),
            FOREIGN KEY (clinica_id, telefono_confirmado_por) REFERENCES personal (clinica_id, id),
            FOREIGN KEY (clinica_id, optin_atestado_por) REFERENCES personal (clinica_id, id),
            FOREIGN KEY (clinica_id, creado_por) REFERENCES personal (clinica_id, id),
            -- Sin casilla de la clínica no hay solicitud, ni respuesta, ni aceptación.
            CONSTRAINT ck_optin_requiere_casilla
                CHECK (optin_estado = 'sin_solicitar' OR optin_atestado_en IS NOT NULL)
        )
        """
    )
    op.execute("CREATE INDEX ON paciente (clinica_id, telefono_idx)")

    # --- paciente_medico (visibilidad del médico; el rol médico lo valida la aplicación) --
    op.execute(
        f"""
        CREATE TABLE paciente_medico (
            {CID},
            paciente_id uuid NOT NULL,
            personal_id uuid NOT NULL,
            PRIMARY KEY (paciente_id, personal_id),
            FOREIGN KEY (clinica_id, paciente_id) REFERENCES paciente (clinica_id, id)
                ON DELETE CASCADE,
            FOREIGN KEY (clinica_id, personal_id) REFERENCES personal (clinica_id, id)
        )
        """
    )
    op.execute("CREATE INDEX ON paciente_medico (clinica_id, personal_id)")

    # --- evento_agenda -----------------------------------------------------------------
    # consulta y procedimiento exigen paciente; otra y bloqueo nunca lo llevan.
    # La longitud del comentario (≤500) la valida la aplicación (está cifrado).
    op.execute(
        f"""
        CREATE TABLE evento_agenda (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            {CID},
            tipo text NOT NULL
                CHECK (tipo IN ('consulta', 'procedimiento', 'otra', 'bloqueo')),
            medico_id uuid NOT NULL,
            sala_id uuid,
            paciente_id uuid,
            rango tstzrange NOT NULL,
            estado text NOT NULL DEFAULT 'pendiente_envio'
                CHECK (estado IN ('pendiente_envio', 'enviado', 'confirmada', 'cancelada')),
            comentario bytea,
            cancelada_por text CHECK (cancelada_por IN ('paciente', 'personal')),
            enviado_en timestamptz,
            confirmado_en timestamptz,
            creado_por uuid NOT NULL,
            actualizado_por uuid NOT NULL,
            creado_en timestamptz NOT NULL DEFAULT now(),
            actualizado_en timestamptz NOT NULL DEFAULT now(),
            UNIQUE (clinica_id, id),
            FOREIGN KEY (clinica_id, medico_id) REFERENCES personal (clinica_id, id),
            FOREIGN KEY (clinica_id, sala_id) REFERENCES sala (clinica_id, id),
            FOREIGN KEY (clinica_id, paciente_id) REFERENCES paciente (clinica_id, id),
            FOREIGN KEY (clinica_id, creado_por) REFERENCES personal (clinica_id, id),
            FOREIGN KEY (clinica_id, actualizado_por) REFERENCES personal (clinica_id, id),
            CONSTRAINT ck_evento_rango CHECK (
                NOT isempty(rango) AND NOT lower_inf(rango) AND NOT upper_inf(rango)
                AND upper(rango) - lower(rango) >= interval '15 minutes'
            ),
            CONSTRAINT ck_evento_paciente CHECK (
                (tipo IN ('consulta', 'procedimiento') AND paciente_id IS NOT NULL)
                OR (tipo IN ('otra', 'bloqueo') AND paciente_id IS NULL)
            ),
            CONSTRAINT ck_evento_estado_sin_paciente CHECK (
                tipo IN ('consulta', 'procedimiento') OR estado IN ('confirmada', 'cancelada')
            ),
            CONSTRAINT ck_evento_cancelada CHECK (
                (estado = 'cancelada') = (cancelada_por IS NOT NULL)
            )
        )
        """
    )
    # Sin doble reserva: por médico y por sala (ignorando eventos cancelados).
    op.execute(
        """
        ALTER TABLE evento_agenda
            ADD CONSTRAINT ex_evento_medico
                EXCLUDE USING gist (medico_id WITH =, rango WITH &&)
                WHERE (estado <> 'cancelada'),
            ADD CONSTRAINT ex_evento_sala
                EXCLUDE USING gist (sala_id WITH =, rango WITH &&)
                WHERE (sala_id IS NOT NULL AND estado <> 'cancelada')
        """
    )
    op.execute("CREATE INDEX ON evento_agenda (clinica_id, paciente_id)")
    op.execute("CREATE INDEX ON evento_agenda (clinica_id, estado)")

    # --- notificacion (alertas internas al personal; sin datos personales) -------------
    op.execute(
        f"""
        CREATE TABLE notificacion (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            {CID},
            destinatario_id uuid NOT NULL,
            tipo text NOT NULL CHECK (
                tipo IN ('sin_confirmar', 'envio_fallido', 'cancelada_por_paciente', 'baja')
            ),
            evento_id uuid,
            creada_en timestamptz NOT NULL DEFAULT now(),
            leida_en timestamptz,
            FOREIGN KEY (clinica_id, destinatario_id) REFERENCES personal (clinica_id, id),
            FOREIGN KEY (clinica_id, evento_id) REFERENCES evento_agenda (clinica_id, id)
                ON DELETE CASCADE
        )
        """
    )
    op.execute("CREATE INDEX ON notificacion (clinica_id, destinatario_id, leida_en)")

    # --- aceptacion_legal --------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE aceptacion_legal (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            {CID},
            usuario_id uuid NOT NULL REFERENCES usuario(id),
            documento text NOT NULL CHECK (documento IN ('terminos', 'aviso')),
            version text NOT NULL,
            aceptado_en timestamptz NOT NULL DEFAULT now(),
            ip inet
        )
        """
    )

    # --- RLS por clínica ---------------------------------------------------------------
    for tabla in TABLAS_CLINICA:
        _aislar(tabla)

    # clinica: `app` solo ve y configura la suya; `operador` ve y gestiona todas;
    # `migrador` solo lee (lo necesita la función de login, que le pertenece).
    op.execute("ALTER TABLE clinica ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE clinica FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY aislamiento_clinica ON clinica TO app
            USING (id = {CONTEXTO}) WITH CHECK (id = {CONTEXTO})
        """
    )
    op.execute("CREATE POLICY operador_total ON clinica TO operador USING (true) WITH CHECK (true)")
    op.execute("CREATE POLICY lectura_login ON clinica FOR SELECT TO migrador USING (true)")
    op.execute("CREATE POLICY lectura_login ON personal FOR SELECT TO migrador USING (true)")

    # auditoria: `app` inserta eventos de plataforma (clinica_id nulo) o de su clínica,
    # y lee solo los de su clínica. `operador` solo inserta.
    op.execute(f"ALTER TABLE auditoria ALTER COLUMN clinica_id SET DEFAULT {CONTEXTO}")
    op.execute("ALTER TABLE auditoria ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE auditoria FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY app_inserta ON auditoria FOR INSERT TO app
            WITH CHECK (clinica_id IS NULL OR clinica_id = {CONTEXTO})
        """
    )
    op.execute(
        f"CREATE POLICY app_lee ON auditoria FOR SELECT TO app USING (clinica_id = {CONTEXTO})"
    )
    op.execute(
        "CREATE POLICY operador_inserta ON auditoria FOR INSERT TO operador WITH CHECK (true)"
    )

    # --- Enlaces con tablas existentes ---------------------------------------------------
    op.execute(
        "ALTER TABLE invitacion ADD CONSTRAINT invitacion_clinica_fk "
        "FOREIGN KEY (clinica_id) REFERENCES clinica(id)"
    )
    # La sesión recuerda el contexto elegido (nulo para el operador y en el paso intermedio).
    op.execute(
        """
        ALTER TABLE sesion
            ADD COLUMN clinica_id uuid REFERENCES clinica(id),
            ADD COLUMN personal_id uuid,
            ADD FOREIGN KEY (clinica_id, personal_id) REFERENCES personal (clinica_id, id)
        """
    )

    # --- Permisos ----------------------------------------------------------------------
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON aceptacion_legal FROM app")  # solo agrega
    op.execute("REVOKE INSERT, DELETE, TRUNCATE ON clinica FROM app")  # la crea el operador
    op.execute("REVOKE UPDATE ON clinica FROM app")
    op.execute(
        "GRANT UPDATE (nombre, zona_horaria, google_maps_url, politica_cancelacion, "
        "plantilla_recordatorio, horario_laboral) ON clinica TO app"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON clinica TO operador")

    # --- Función de login: clínicas de un usuario (sin contexto de clínica) --------------
    op.execute(
        """
        CREATE FUNCTION clinicas_de_usuario(p_usuario_id uuid)
        RETURNS TABLE (clinica_id uuid, personal_id uuid, rol text, clinica_nombre text)
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT p.clinica_id, p.id, p.rol, c.nombre
            FROM personal p
            JOIN clinica c ON c.id = p.clinica_id
            WHERE p.usuario_id = p_usuario_id
              AND p.activo
              AND c.estado <> 'suspendida'
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION clinicas_de_usuario(uuid) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION clinicas_de_usuario(uuid) TO app")


def downgrade() -> None:
    op.execute("DROP FUNCTION clinicas_de_usuario(uuid)")
    op.execute("ALTER TABLE sesion DROP COLUMN personal_id, DROP COLUMN clinica_id")
    op.execute("ALTER TABLE invitacion DROP CONSTRAINT invitacion_clinica_fk")

    for politica in ("app_inserta", "app_lee", "operador_inserta"):
        op.execute(f"DROP POLICY {politica} ON auditoria")
    op.execute("ALTER TABLE auditoria NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE auditoria DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE auditoria ALTER COLUMN clinica_id DROP DEFAULT")

    for tabla in (
        "aceptacion_legal",
        "notificacion",
        "evento_agenda",
        "paciente_medico",
        "paciente",
        "sala",
        "personal",
        "clinica",
    ):
        op.execute(f"DROP TABLE {tabla}")

    # Deja la cadena consistente con el downgrade de 0001.
    op.execute(
        """
        CREATE TABLE _rls_demo (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            clinica_id uuid NOT NULL,
            dato text NOT NULL
        )
        """
    )
    op.execute("ALTER TABLE _rls_demo ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE _rls_demo FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY aislamiento_clinica ON _rls_demo
            USING (clinica_id = {CONTEXTO})
            WITH CHECK (clinica_id = {CONTEXTO})
        """
    )
