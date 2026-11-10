"""Pertenencia a una clínica: contexto RLS, DEK de la clínica, alta de personal."""

from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto.envelope import unwrap_dek
from app.crypto.fields import FieldCipher, FieldContext
from app.crypto.keys import KeyProvider


async def fijar_contexto(db: AsyncSession, clinica_id: UUID) -> None:
    """Equivale a SET LOCAL: dura hasta el commit/rollback de la transacción."""
    await db.execute(text("SELECT set_config('app.clinica_id', :c, true)"), {"c": str(clinica_id)})


async def cargar_cipher(db: AsyncSession, provider: KeyProvider, clinica_id: UUID) -> FieldCipher:
    """Requiere el contexto de esa clínica ya fijado (RLS)."""
    row = (
        await db.execute(
            text("SELECT dek_wrapped, dek_version FROM clinica WHERE id = :i"), {"i": clinica_id}
        )
    ).one()
    dek = unwrap_dek(provider, bytes(row.dek_wrapped), f"clinica|{clinica_id}|v{row.dek_version}")
    return FieldCipher({row.dek_version: dek}, row.dek_version)


async def crear_personal(
    db: AsyncSession,
    provider: KeyProvider,
    *,
    clinica_id: UUID,
    usuario_id: UUID,
    rol: str,
    nombre: str,
) -> UUID:
    await fijar_contexto(db, clinica_id)
    cipher = await cargar_cipher(db, provider, clinica_id)
    pid = uuid4()
    await db.execute(
        text("INSERT INTO personal (id, usuario_id, rol, nombre) VALUES (:i, :u, :r, :n)"),
        {
            "i": pid,
            "u": usuario_id,
            "r": rol,
            "n": cipher.encrypt(nombre, FieldContext("personal", "nombre", clinica_id, pid)),
        },
    )
    return pid


async def registrar_aceptacion(
    db: AsyncSession, usuario_id: UUID, version: str, ip: str | None
) -> None:
    """Requiere el contexto de la clínica fijado."""
    for documento in ("terminos", "aviso"):
        await db.execute(
            text(
                "INSERT INTO aceptacion_legal (usuario_id, documento, version, ip) "
                "VALUES (:u, :d, :v, CAST(:ip AS inet))"
            ),
            {"u": usuario_id, "d": documento, "v": version, "ip": ip},
        )
