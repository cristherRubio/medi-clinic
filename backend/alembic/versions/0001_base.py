"""Base: extensión btree_gist y tabla de demostración de RLS.

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONTEXTO = "nullif(current_setting('app.clinica_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    # La tabla de versiones no es para la aplicación.
    op.execute("REVOKE ALL ON alembic_version FROM app, operador")

    # Plantilla de RLS. La Fase 1 la elimina y aplica el mismo patrón a las tablas reales.
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


def downgrade() -> None:
    op.execute("DROP TABLE _rls_demo")
    op.execute("DROP EXTENSION IF EXISTS btree_gist")
