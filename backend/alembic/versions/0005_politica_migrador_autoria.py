"""Política de inserción en auditoría para `migrador` (bootstrap).

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE POLICY migrador_inserta ON auditoria FOR INSERT TO migrador WITH CHECK (true)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY migrador_inserta ON auditoria")
