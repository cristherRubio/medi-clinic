"""El operador puede borrar sesiones por clínica (suspensión inmediata).

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SELECT solo de clinica_id (necesario para el WHERE del DELETE); nunca ve tokens.
    op.execute("GRANT SELECT (clinica_id) ON sesion TO operador")
    op.execute("GRANT DELETE ON sesion TO operador")


def downgrade() -> None:
    op.execute("REVOKE DELETE ON sesion FROM operador")
    op.execute("REVOKE SELECT (clinica_id) ON sesion FROM operador")
