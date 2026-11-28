"""Entrega de invitaciones: por correo si hay proveedor; si no, el token vuelve en la respuesta.

El correo se envía antes del commit: si el proveedor falla, se deshace todo y se responde
502, para que no quede una invitación que nadie recibió y cuyo token ya no se puede ver.
"""

import logging

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.correo import CorreoError, EmailProvider, invitacion

log = logging.getLogger(__name__)


async def entregar_invitacion(
    db: AsyncSession,
    proveedor: EmailProvider,
    *,
    email: str,
    clinica: str,
    rol: str,
    token: str,
) -> bool:
    """True si se envió por correo; False si no hay proveedor (entrega a mano)."""
    if not proveedor.activo:
        return False
    settings = get_settings()
    try:
        await proveedor.enviar(
            invitacion(settings, email, clinica, rol, token, settings.invitacion_horas)
        )
    except CorreoError as e:
        await db.rollback()
        log.warning("No se pudo enviar el correo de invitación: %s", e)
        raise HTTPException(502, "No se pudo enviar el correo de invitación") from None
    return True
