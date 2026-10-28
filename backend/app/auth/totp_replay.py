"""Impide reutilizar un código TOTP: solo acepta pasos mayores al último usado."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def consumir_paso(session: AsyncSession, usuario_id: UUID, paso: int) -> bool:
    """True si el paso era nuevo (y queda registrado); False si ya se usó."""
    res = await session.execute(
        text(
            "UPDATE usuario SET totp_ultimo_paso = :p WHERE id = :u "
            "AND (totp_ultimo_paso IS NULL OR totp_ultimo_paso < :p) RETURNING id"
        ),
        {"p": paso, "u": usuario_id},
    )
    return res.first() is not None
