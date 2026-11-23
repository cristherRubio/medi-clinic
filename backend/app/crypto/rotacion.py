"""Rotación de llaves por lotes. La usa `app/scripts/rotacion.py` y corre como `migrador`.

- **KEK** (llave maestra): `rotar_kek` reenvuelve cada DEK (plataforma y clínicas, activa y
  anterior) con la KEK activa. Los datos no se tocan. Idempotente.
- **DEK de clínica**: `rotar_dek_clinica` crea la DEK v(n+1), deja la actual como "anterior"
  (la API la sigue usando para leer), recifra por lotes todo lo que no esté en la versión
  nueva y, cuando no queda nada, borra la anterior. Si se interrumpe, al volver a correr
  continúa donde se quedó. Mientras haya una rotación en curso no empieza otra.

Todo queda en `auditoria` sin datos personales (solo ids, versiones y conteos).
"""

import asyncio
import struct
from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.auth import audit, membership
from app.auth.membership import contexto_dek
from app.crypto.columnas import COLUMNAS_CLINICA, params
from app.crypto.envelope import generate_dek, kek_version_of, rewrap_dek, wrap_dek
from app.crypto.errors import DecryptionError
from app.crypto.keys import KeyProvider

_VERSION = struct.Struct(">I")  # así va la versión de la DEK en cada valor cifrado


class RotacionError(RuntimeError):
    pass


# --- KEK ---------------------------------------------------------------------------------


async def _ids_clinicas(engine: AsyncEngine) -> list[UUID]:
    async with AsyncSession(engine) as db:
        return list(
            (await db.execute(text("SELECT id FROM clinica ORDER BY creado_en, id"))).scalars()
        )


async def rotar_kek(
    engine: AsyncEngine,
    provider: KeyProvider,
    *,
    clinicas: Sequence[UUID] | None = None,
    plataforma: bool = True,
) -> int:
    """Reenvuelve con la KEK activa las DEK que estén en otra versión. Devuelve cuántas.

    `clinicas` y `plataforma` acotan el alcance (pruebas); por defecto, todo.
    """
    activa = provider.active_version
    reenvueltas = 0
    if plataforma:
        async with AsyncSession(engine) as db:
            filas = (
                await db.execute(
                    text("SELECT version, dek_wrapped FROM llave_plataforma ORDER BY version")
                )
            ).all()
            for f in filas:
                if kek_version_of(bytes(f.dek_wrapped)) != activa:
                    nueva = rewrap_dek(provider, bytes(f.dek_wrapped), f"plataforma|v{f.version}")
                    await db.execute(
                        text("UPDATE llave_plataforma SET dek_wrapped = :w WHERE version = :v"),
                        {"w": nueva, "v": f.version},
                    )
                    reenvueltas += 1
            await db.commit()

    for cid in clinicas if clinicas is not None else await _ids_clinicas(engine):
        async with AsyncSession(engine) as db:
            f = (
                await db.execute(
                    text(
                        "SELECT dek_wrapped, dek_version, dek_anterior_wrapped, "
                        "dek_anterior_version FROM clinica WHERE id = :c FOR UPDATE"
                    ),
                    {"c": cid},
                )
            ).one()
            activa_w, anterior_w = bytes(f.dek_wrapped), f.dek_anterior_wrapped
            cambios = 0
            if kek_version_of(activa_w) != activa:
                activa_w = rewrap_dek(provider, activa_w, contexto_dek(cid, f.dek_version))
                cambios += 1
            if anterior_w is not None and kek_version_of(bytes(anterior_w)) != activa:
                anterior_w = rewrap_dek(
                    provider, bytes(anterior_w), contexto_dek(cid, f.dek_anterior_version)
                )
                cambios += 1
            if cambios:
                await db.execute(
                    text(
                        "UPDATE clinica SET dek_wrapped = :w, dek_anterior_wrapped = :a "
                        "WHERE id = :c"
                    ),
                    {"w": activa_w, "a": anterior_w, "c": cid},
                )
                reenvueltas += cambios
            await db.commit()

    async with AsyncSession(engine) as db:
        await audit.registrar(
            db,
            accion="kek_rotada",
            entidad="kek",
            metadata={"kek_version": activa, "reenvueltas": reenvueltas},
        )
        await db.commit()
    return reenvueltas


# --- DEK de clínica ---------------------------------------------------------------------


@dataclass(frozen=True)
class ResultadoDek:
    clinica_id: UUID
    dek_version: int
    recifrados: int
    nueva: bool  # False = se reanudó una rotación que estaba en curso


async def iniciar_rotacion_dek(engine: AsyncEngine, provider: KeyProvider, cid: UUID) -> bool:
    """Crea la DEK nueva y deja la actual como anterior. False si ya había una en curso."""
    async with AsyncSession(engine) as db:
        f = (
            await db.execute(
                text(
                    "SELECT dek_version, dek_anterior_version FROM clinica WHERE id = :c FOR UPDATE"
                ),
                {"c": cid},
            )
        ).one()
        if f.dek_anterior_version is not None:
            await db.commit()
            return False
        nueva = f.dek_version + 1
        await db.execute(
            text(
                "UPDATE clinica SET dek_anterior_wrapped = dek_wrapped, "
                "dek_anterior_version = dek_version, dek_wrapped = :w, dek_version = :v "
                "WHERE id = :c"
            ),
            {
                "w": wrap_dek(provider, generate_dek(), contexto_dek(cid, nueva)),
                "v": nueva,
                "c": cid,
            },
        )
        await audit.registrar(
            db,
            accion="dek_rotacion_iniciada",
            clinica_id=cid,
            entidad="clinica",
            entidad_id=cid,
            metadata={"dek_version": nueva},
        )
        await db.commit()
        return True


async def _recifrar(engine: AsyncEngine, provider: KeyProvider, cid: UUID, lote: int) -> int:
    async with AsyncSession(engine) as db:
        cipher = await membership.cargar_cipher(db, provider, cid)
        await db.commit()
    version = _VERSION.pack(cipher.active_version)
    total = 0
    for col in COLUMNAS_CLINICA:
        while True:
            async with AsyncSession(engine) as db:
                filas = (await db.execute(col.leer, params(cid, version, lote))).all()
                for f in filas:
                    nuevo = cipher.reencrypt(bytes(f.valor), col.contexto(cid, f.id))
                    await db.execute(col.escribir, {"valor": nuevo, "i": f.id})
                await db.commit()
            total += len(filas)
            if len(filas) < lote:
                break
    return total


async def _terminar(engine: AsyncEngine, cid: UUID, recifrados: int) -> bool:
    """Borra la DEK anterior si ya no queda nada cifrado con ella."""
    async with AsyncSession(engine) as db:
        f = (
            await db.execute(
                text(
                    "SELECT dek_version, dek_anterior_version FROM clinica WHERE id = :c FOR UPDATE"
                ),
                {"c": cid},
            )
        ).one()
        if f.dek_anterior_version is None:
            await db.commit()
            return True
        version = _VERSION.pack(f.dek_version)
        for col in COLUMNAS_CLINICA:
            if (await db.execute(col.contar, params(cid, version))).scalar_one():
                await db.rollback()
                return False
        await db.execute(
            text(
                "UPDATE clinica SET dek_anterior_wrapped = NULL, dek_anterior_version = NULL "
                "WHERE id = :c"
            ),
            {"c": cid},
        )
        await audit.registrar(
            db,
            accion="dek_clinica_rotada",
            clinica_id=cid,
            entidad="clinica",
            entidad_id=cid,
            metadata={"dek_version": f.dek_version, "recifrados": recifrados},
        )
        await db.commit()
        return True


async def rotar_dek_clinica(
    engine: AsyncEngine,
    provider: KeyProvider,
    cid: UUID,
    *,
    lote: int = 500,
    espera: float = 10.0,
    max_pasadas: int = 5,
) -> ResultadoDek:
    """Rota (o termina de rotar) la DEK de una clínica.

    `espera`: segundos de gracia tras crear la DEK nueva, para que terminen las peticiones
    de la API que ya habían cargado la anterior (podrían escribir con ella). Lo que escriban
    después igual se detecta: no se borra la DEK anterior mientras quede algo cifrado con ella.
    """
    nueva = await iniciar_rotacion_dek(engine, provider, cid)
    if nueva and espera > 0:
        await asyncio.sleep(espera)
    total = 0
    for _ in range(max_pasadas):
        total += await _recifrar(engine, provider, cid, lote)
        if await _terminar(engine, cid, total):
            async with AsyncSession(engine) as db:
                version = (
                    await db.execute(
                        text("SELECT dek_version FROM clinica WHERE id = :c"), {"c": cid}
                    )
                ).scalar_one()
            return ResultadoDek(cid, version, total, nueva)
    raise RotacionError(f"Clínica {cid}: siguen apareciendo valores con la DEK anterior")


async def rotar_dek_todas(
    engine: AsyncEngine, provider: KeyProvider, *, lote: int = 500, espera: float = 10.0
) -> list[ResultadoDek]:
    return [
        await rotar_dek_clinica(engine, provider, cid, lote=lote, espera=espera)
        for cid in await _ids_clinicas(engine)
    ]


# --- Estado ------------------------------------------------------------------------------


@dataclass(frozen=True)
class EstadoClinica:
    clinica_id: UUID
    dek_version: int
    en_rotacion: bool
    kek_versiones: frozenset[int]


@dataclass
class Estado:
    kek_activa: int
    plataforma: dict[int, int] = field(default_factory=dict)  # versión DEK → versión KEK
    clinicas: list[EstadoClinica] = field(default_factory=list)

    def pendientes(self) -> list[str]:
        """Lo que impide dar por terminada una rotación (vacío = todo en orden)."""
        avisos = [
            f"DEK de plataforma v{dek} envuelta con KEK v{kek}"
            for dek, kek in self.plataforma.items()
            if kek != self.kek_activa
        ]
        for c in self.clinicas:
            if c.en_rotacion:
                avisos.append(f"Clínica {c.clinica_id}: rotación de DEK en curso")
            if c.kek_versiones - {self.kek_activa}:
                avisos.append(f"Clínica {c.clinica_id}: DEK envuelta con una KEK anterior")
        return avisos


def _kek_o_cero(wrapped: bytes) -> int:
    """Versión de KEK; 0 si la DEK envuelta está dañada (se reporta, no se detiene)."""
    try:
        return kek_version_of(wrapped)
    except DecryptionError:
        return 0


async def estado(engine: AsyncEngine, kek_activa: int) -> Estado:
    resultado = Estado(kek_activa)
    async with AsyncSession(engine) as db:
        for f in await db.execute(text("SELECT version, dek_wrapped FROM llave_plataforma")):
            resultado.plataforma[f.version] = _kek_o_cero(bytes(f.dek_wrapped))
        filas = await db.execute(
            text(
                "SELECT id, dek_wrapped, dek_version, dek_anterior_wrapped FROM clinica "
                "ORDER BY creado_en, id"
            )
        )
        for f in filas:
            keks = {_kek_o_cero(bytes(f.dek_wrapped))}
            if f.dek_anterior_wrapped is not None:
                keks.add(_kek_o_cero(bytes(f.dek_anterior_wrapped)))
            resultado.clinicas.append(
                EstadoClinica(
                    f.id, f.dek_version, f.dek_anterior_wrapped is not None, frozenset(keks)
                )
            )
    return resultado
