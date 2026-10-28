"""Límite de intentos fallidos, guardado en la BD. Solo cuentan los fallos.

`clave_hash` es un HMAC de la cuenta (email normalizado) o de la IP: nunca el dato en claro.
Un login exitoso limpia los fallos de la cuenta, pero NO los de la IP.
Quien llama debe hacer commit del fallo aunque responda con error.
"""

import hashlib
import hmac
from typing import Literal

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings

Tipo = Literal["login_cuenta", "login_ip", "activar_ip", "activar_token"]


def derive_throttle_key(kek: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"throttle").derive(kek)


def clave_hash(key: bytes, tipo: Tipo, valor: str) -> bytes:
    return hmac.new(key, f"{tipo}|{valor}".encode(), hashlib.sha256).digest()


def limite(tipo: Tipo, settings: Settings | None = None) -> tuple[int, int]:
    """(máximo de fallos, ventana en minutos)."""
    s = settings or get_settings()
    if tipo == "login_cuenta":
        return s.login_cuenta_max, s.login_cuenta_ventana_min
    if tipo == "login_ip":
        return s.login_ip_max, s.login_ip_ventana_min
    if tipo == "activar_token":
        return s.activar_token_max, s.activar_token_ventana_min
    return s.activar_ip_max, s.activar_ip_ventana_min


async def registrar_fallo(session: AsyncSession, clave: bytes, tipo: Tipo) -> None:
    await session.execute(
        text("INSERT INTO intento_login (clave_hash, tipo) VALUES (:c, :t)"),
        {"c": clave, "t": tipo},
    )


async def esta_bloqueado(session: AsyncSession, clave: bytes, tipo: Tipo) -> bool:
    maximo, ventana = limite(tipo)
    total = (
        await session.execute(
            text(
                "SELECT count(*) FROM intento_login WHERE clave_hash = :c AND tipo = :t "
                "AND creado_en > now() - make_interval(mins => :m)"
            ),
            {"c": clave, "t": tipo, "m": ventana},
        )
    ).scalar_one()
    return int(total) >= maximo


async def limpiar_fallos(session: AsyncSession, clave: bytes, tipo: Tipo) -> None:
    await session.execute(
        text("DELETE FROM intento_login WHERE clave_hash = :c AND tipo = :t"),
        {"c": clave, "t": tipo},
    )


async def purgar_antiguos(session: AsyncSession, horas: int = 24) -> None:
    """Para el worker: borra intentos más viejos que cualquier ventana."""
    await session.execute(
        text("DELETE FROM intento_login WHERE creado_en < now() - make_interval(hours => :h)"),
        {"h": horas},
    )
