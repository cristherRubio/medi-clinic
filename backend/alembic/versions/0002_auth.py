"""Autenticación: llave de plataforma, usuario, sesión, invitación, intentos y auditoría.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # DEK de plataforma (cifra los datos de `usuario`), envuelta con la KEK.
    op.execute(
        """
        CREATE TABLE llave_plataforma (
            version int PRIMARY KEY,
            dek_wrapped bytea NOT NULL,
            activa boolean NOT NULL DEFAULT true,
            creado_en timestamptz NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE usuario (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            email bytea NOT NULL,
            email_idx bytea NOT NULL UNIQUE,
            password_hash text,
            totp_secret bytea,
            totp_activo boolean NOT NULL DEFAULT false,
            es_operador boolean NOT NULL DEFAULT false,
            activo boolean NOT NULL DEFAULT true,
            ultimo_login timestamptz,
            creado_en timestamptz NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE codigo_recuperacion (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            usuario_id uuid NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
            codigo_hash bytea NOT NULL UNIQUE,
            usado_en timestamptz
        )
        """
    )
    op.execute("CREATE INDEX ON codigo_recuperacion (usuario_id)")

    # mfa_ok = false: contraseña verificada, falta el TOTP (sesión corta de paso intermedio).
    op.execute(
        """
        CREATE TABLE sesion (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            usuario_id uuid NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
            token_hash bytea NOT NULL UNIQUE,
            mfa_ok boolean NOT NULL DEFAULT false,
            creado_en timestamptz NOT NULL DEFAULT now(),
            ultimo_uso timestamptz NOT NULL DEFAULT now(),
            expira_en timestamptz NOT NULL,
            ip inet
        )
        """
    )
    op.execute("CREATE INDEX ON sesion (usuario_id)")

    # clinica_id sin llave foránea: la tabla `clinica` llega en la Fase 1, que la agrega.
    op.execute(
        """
        CREATE TABLE invitacion (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            email bytea NOT NULL,
            email_idx bytea NOT NULL,
            clinica_id uuid,
            rol text NOT NULL CHECK (rol IN ('admin', 'asistente', 'medico')),
            token_hash bytea NOT NULL UNIQUE,
            expira_en timestamptz NOT NULL,
            usada_en timestamptz,
            creada_por uuid REFERENCES usuario(id),
            creado_en timestamptz NOT NULL DEFAULT now()
        )
        """
    )

    # Límite de intentos. `clave_hash` es un HMAC (de IP o cuenta): nunca el dato en claro.
    op.execute(
        """
        CREATE TABLE intento_login (
            id bigserial PRIMARY KEY,
            clave_hash bytea NOT NULL,
            tipo text NOT NULL,
            creado_en timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ON intento_login (clave_hash, tipo, creado_en)")

    # Sin datos personales en `metadata`.
    op.execute(
        """
        CREATE TABLE auditoria (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            clinica_id uuid,
            actor_usuario_id uuid,
            accion text NOT NULL,
            entidad text,
            entidad_id uuid,
            ip inet,
            metadata jsonb NOT NULL DEFAULT '{}',
            creado_en timestamptz NOT NULL DEFAULT now()
        )
        """
    )

    # Permisos. `app` ya recibe CRUD por defecto; aquí se recortan los casos especiales.
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON auditoria FROM app")  # solo se agrega
    op.execute("REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON llave_plataforma FROM app")  # solo lee

    # Operador: solo usuario, invitación y lo mínimo para auditar y descifrar sus datos.
    op.execute("GRANT SELECT, INSERT, UPDATE ON usuario, invitacion TO operador")
    op.execute("GRANT SELECT ON llave_plataforma TO operador")
    op.execute("GRANT INSERT ON auditoria TO operador")


def downgrade() -> None:
    for tabla in (
        "auditoria",
        "intento_login",
        "invitacion",
        "sesion",
        "codigo_recuperacion",
        "usuario",
        "llave_plataforma",
    ):
        op.execute(f"DROP TABLE {tabla}")
