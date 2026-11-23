"""Rotación de llaves: DEK anterior de la clínica y permisos de `migrador` para recifrar.

Durante una rotación la clínica tiene dos DEK: la activa (cifra lo nuevo) y la anterior
(solo descifra lo que falta recifrar). Al terminar, la anterior se borra.
`migrador` (scripts de mantenimiento, nunca la API) puede leer y actualizar las tablas
con campos cifrados de clínica; `app` sigue sin poder tocar las columnas de llaves.

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE clinica
            ADD COLUMN dek_anterior_wrapped bytea,
            ADD COLUMN dek_anterior_version int,
            ADD CONSTRAINT ck_dek_anterior
                CHECK ((dek_anterior_wrapped IS NULL) = (dek_anterior_version IS NULL))
        """
    )
    # clinica y personal ya tienen lectura para migrador (lectura_login).
    op.execute(
        "CREATE POLICY migrador_rotacion ON clinica FOR UPDATE TO migrador "
        "USING (true) WITH CHECK (true)"
    )
    op.execute(
        "CREATE POLICY migrador_rotacion ON personal FOR UPDATE TO migrador "
        "USING (true) WITH CHECK (true)"
    )
    for tabla in ("paciente", "evento_agenda"):
        op.execute(f"CREATE POLICY migrador_lee ON {tabla} FOR SELECT TO migrador USING (true)")
        op.execute(
            f"CREATE POLICY migrador_rotacion ON {tabla} FOR UPDATE TO migrador "
            "USING (true) WITH CHECK (true)"
        )


def downgrade() -> None:
    for tabla in ("paciente", "evento_agenda"):
        op.execute(f"DROP POLICY migrador_rotacion ON {tabla}")
        op.execute(f"DROP POLICY migrador_lee ON {tabla}")
    op.execute("DROP POLICY migrador_rotacion ON personal")
    op.execute("DROP POLICY migrador_rotacion ON clinica")
    op.execute(
        "ALTER TABLE clinica DROP CONSTRAINT ck_dek_anterior, "
        "DROP COLUMN dek_anterior_version, DROP COLUMN dek_anterior_wrapped"
    )
