"""Último paso TOTP aceptado, para impedir reutilizar un código.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE usuario ADD COLUMN totp_ultimo_paso bigint")


def downgrade() -> None:
    op.execute("ALTER TABLE usuario DROP COLUMN totp_ultimo_paso")
