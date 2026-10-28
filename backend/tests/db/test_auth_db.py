"""Throttle, auditoría y reutilización de TOTP contra la BD. Solo con APP_TEST_DB=1."""

import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from app.auth import audit, throttle
from app.auth.totp_replay import consumir_paso
from app.db.session import make_engine
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.skipif(
    os.environ.get("APP_TEST_DB") != "1", reason="Pruebas de BD: solo en CI (APP_TEST_DB=1)"
)

KEY = throttle.derive_throttle_key(b"k" * 32)


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = make_engine("app")
    async with AsyncSession(engine) as s:
        yield s
        await s.commit()
    await engine.dispose()


async def _viejos(s: AsyncSession, clave: bytes, tipo: str, n: int, minutos: int) -> None:
    for _ in range(n):
        await s.execute(
            text(
                "INSERT INTO intento_login (clave_hash, tipo, creado_en) "
                "VALUES (:c, :t, now() - make_interval(mins => :m))"
            ),
            {"c": clave, "t": tipo, "m": minutos},
        )


@pytest.mark.asyncio
async def test_bloqueo_por_cuenta_y_limpieza(session: AsyncSession) -> None:
    c = throttle.clave_hash(KEY, "login_cuenta", uuid4().hex)
    for _ in range(4):
        await throttle.registrar_fallo(session, c, "login_cuenta")
    assert not await throttle.esta_bloqueado(session, c, "login_cuenta")
    await throttle.registrar_fallo(session, c, "login_cuenta")
    assert await throttle.esta_bloqueado(session, c, "login_cuenta")
    await throttle.limpiar_fallos(session, c, "login_cuenta")
    assert not await throttle.esta_bloqueado(session, c, "login_cuenta")


@pytest.mark.asyncio
async def test_ventanas_deslizantes(session: AsyncSession) -> None:
    c = throttle.clave_hash(KEY, "login_cuenta", uuid4().hex)
    await _viejos(session, c, "login_cuenta", 5, 10)  # fuera de 5 min
    assert not await throttle.esta_bloqueado(session, c, "login_cuenta")
    i = throttle.clave_hash(KEY, "login_ip", uuid4().hex)
    await _viejos(session, i, "login_ip", 20, 10)  # dentro de 20 min
    assert await throttle.esta_bloqueado(session, i, "login_ip")


@pytest.mark.asyncio
async def test_tipos_no_se_mezclan(session: AsyncSession) -> None:
    c = throttle.clave_hash(KEY, "login_cuenta", uuid4().hex)
    for _ in range(5):
        await throttle.registrar_fallo(session, c, "login_cuenta")
    assert not await throttle.esta_bloqueado(session, c, "login_ip")


@pytest.mark.asyncio
async def test_auditoria_inserta_y_rechaza_datos_personales(session: AsyncSession) -> None:
    ent = uuid4()
    await audit.registrar(
        session, accion="prueba", entidad="x", entidad_id=ent, ip="127.0.0.1", metadata={"k": 1}
    )
    n = (
        await session.execute(
            text("SELECT count(*) FROM auditoria WHERE entidad_id = :e"), {"e": ent}
        )
    ).scalar_one()
    assert n == 1
    with pytest.raises(audit.AuditMetadataError):
        await audit.registrar(session, accion="prueba", metadata={"email": "a@b.c"})


@pytest.mark.asyncio
async def test_auditoria_es_solo_insercion(session: AsyncSession) -> None:
    from sqlalchemy.exc import DBAPIError

    with pytest.raises(DBAPIError):
        await session.execute(text("UPDATE auditoria SET accion = 'x'"))


@pytest.mark.asyncio
async def test_totp_no_se_reutiliza(session: AsyncSession) -> None:
    uid = uuid4()
    await session.execute(
        text("INSERT INTO usuario (id, email, email_idx) VALUES (:i, :e, :x)"),
        {"i": uid, "e": b"cifrado", "x": uid.bytes},
    )
    assert await consumir_paso(session, uid, 100)
    assert not await consumir_paso(session, uid, 100)
    assert not await consumir_paso(session, uid, 99)
    assert await consumir_paso(session, uid, 101)
