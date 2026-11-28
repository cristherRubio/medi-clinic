"""Restablecimiento de contraseña por correo.

Token de un solo uso (solo su hash), con vencimiento. Sin RLS: se busca por token antes de
haber sesión (como `invitacion`). `app` lo usa; `operador` no tiene permisos.

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE restablecimiento (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            usuario_id uuid NOT NULL REFERENCES usuario(id),
            token_hash bytea NOT NULL UNIQUE,
            creado_en timestamptz NOT NULL DEFAULT now(),
            expira_en timestamptz NOT NULL,
            usado_en timestamptz
        )
        """
    )
    op.execute("CREATE INDEX ON restablecimiento (usuario_id) WHERE usado_en IS NULL")
    op.execute("REVOKE DELETE, TRUNCATE ON restablecimiento FROM app")


def downgrade() -> None:
    op.execute("DROP TABLE restablecimiento")
