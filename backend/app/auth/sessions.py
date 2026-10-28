"""Sesiones del lado del servidor (tabla `sesion`) y token CSRF derivado."""

import hashlib
import hmac
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import hash_token, new_token
from app.config import Settings


def cookie_names(settings: Settings) -> tuple[str, str]:
    """(sesión, csrf). Con prefijo __Host- cuando hay HTTPS."""
    prefijo = "__Host-" if settings.cookie_secure else ""
    return f"{prefijo}sid", f"{prefijo}csrf"


def csrf_for(key: bytes, token: str) -> str:
    return hmac.new(key, token.encode(), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class SessionData:
    id: UUID
    usuario_id: UUID
    mfa_ok: bool
    token: str


async def crear(
    db: AsyncSession, usuario_id: UUID, *, mfa_ok: bool, ip: str | None, settings: Settings
) -> str:
    """Crea la sesión y devuelve el token en claro (solo va en la cookie)."""
    token = new_token()
    minutos = settings.session_max_hours * 60 if mfa_ok else settings.sesion_pendiente_min
    await db.execute(
        text(
            "INSERT INTO sesion (usuario_id, token_hash, mfa_ok, expira_en, ip) "
            "VALUES (:u, :h, :m, now() + make_interval(mins => :e), CAST(:ip AS inet))"
        ),
        {"u": usuario_id, "h": hash_token(token), "m": mfa_ok, "e": minutos, "ip": ip},
    )
    return token


async def buscar(db: AsyncSession, token: str, settings: Settings) -> SessionData | None:
    """Sesión vigente (tope absoluto e inactividad) de un usuario activo."""
    row = (
        await db.execute(
            text(
                "SELECT s.id, s.usuario_id, s.mfa_ok, "
                "(s.ultimo_uso < now() - interval '1 minute') AS vieja "
                "FROM sesion s JOIN usuario u ON u.id = s.usuario_id "
                "WHERE s.token_hash = :h AND s.expira_en > now() "
                "AND s.ultimo_uso > now() - make_interval(hours => :i) AND u.activo"
            ),
            {"h": hash_token(token), "i": settings.session_idle_hours},
        )
    ).first()
    if row is None:
        return None
    if row.vieja:
        await db.execute(text("UPDATE sesion SET ultimo_uso = now() WHERE id = :i"), {"i": row.id})
    return SessionData(row.id, row.usuario_id, row.mfa_ok, token)


async def borrar(db: AsyncSession, sesion_id: UUID) -> None:
    await db.execute(text("DELETE FROM sesion WHERE id = :i"), {"i": sesion_id})
