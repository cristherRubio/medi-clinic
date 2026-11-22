"""`migrador` puede leer la auditoría (mantenimiento y pruebas de cobertura de auditoría).

Los eventos sin clínica (login, logout, activación) no los puede leer ningún rol de la
aplicación; `migrador` nunca se entrega a la API.

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE POLICY migrador_lee ON auditoria FOR SELECT TO migrador USING (true)")


def downgrade() -> None:
    op.execute("DROP POLICY migrador_lee ON auditoria")
