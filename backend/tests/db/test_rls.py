"""Aislamiento entre clínicas con RLS. Solo corre con APP_TEST_DB=1 (CI)."""

import os
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from app.db.session import clinic_session, make_engine
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.skipif(
    os.environ.get("APP_TEST_DB") != "1", reason="Pruebas de BD: solo en CI (APP_TEST_DB=1)"
)

INSERTAR = text("INSERT INTO sala (clinica_id, nombre) VALUES (:c, :d)")
INSERTAR_CLINICA = text(
    """
    INSERT INTO clinica (id, nombre, tipo_persona, nombre_legal, rfc,
                         representante_nombre, representante_curp, dek_wrapped)
    VALUES (:id, 'test', 'fisica', 'test', :b, :b, :b, :b)
    """
)


@pytest_asyncio.fixture
async def app_engine() -> AsyncIterator[AsyncEngine]:
    engine = make_engine("app")
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def operador_engine() -> AsyncIterator[AsyncEngine]:
    engine = make_engine("operador")
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def clinicas(
    app_engine: AsyncEngine, operador_engine: AsyncEngine
) -> AsyncIterator[tuple[UUID, UUID]]:
    """Dos clínicas de prueba creadas por el operador (única vía de alta)."""
    a, b = uuid4(), uuid4()
    async with operador_engine.begin() as c:
        for cid in (a, b):
            await c.execute(INSERTAR_CLINICA, {"id": cid, "b": b"x"})
    yield a, b
    # Limpia solo sus filas de sala. Las clínicas quedan: nadie tiene DELETE sobre `clinica`.
    for cid in (a, b):
        async with clinic_session(app_engine, cid) as s:
            await s.execute(text("DELETE FROM sala"))


async def _insertar(engine: AsyncEngine, clinica: UUID, dato: str) -> None:
    async with clinic_session(engine, clinica) as s:
        await s.execute(INSERTAR, {"c": clinica, "d": dato})


@pytest.mark.asyncio
async def test_cada_clinica_ve_solo_lo_suyo(
    app_engine: AsyncEngine, clinicas: tuple[UUID, UUID]
) -> None:
    a, b = clinicas
    await _insertar(app_engine, a, "de-a")
    await _insertar(app_engine, b, "de-b")
    async with clinic_session(app_engine, a) as s:
        datos = (await s.execute(text("SELECT nombre FROM sala"))).scalars().all()
    assert datos == ["de-a"]


@pytest.mark.asyncio
async def test_no_puede_insertar_en_otra_clinica(
    app_engine: AsyncEngine, clinicas: tuple[UUID, UUID]
) -> None:
    a, b = clinicas
    with pytest.raises(DBAPIError):
        await _insertar_ajeno(app_engine, contexto=a, destino=b)


async def _insertar_ajeno(engine: AsyncEngine, contexto: UUID, destino: UUID) -> None:
    async with clinic_session(engine, contexto) as s:
        await s.execute(INSERTAR, {"c": destino, "d": "intruso"})


@pytest.mark.asyncio
async def test_no_modifica_ni_borra_filas_ajenas(
    app_engine: AsyncEngine, clinicas: tuple[UUID, UUID]
) -> None:
    a, b = clinicas
    await _insertar(app_engine, b, "de-b")
    async with clinic_session(app_engine, a) as s:
        upd = await s.execute(
            text("UPDATE sala SET nombre = 'x' WHERE clinica_id = :b RETURNING id"), {"b": b}
        )
        dele = await s.execute(
            text("DELETE FROM sala WHERE clinica_id = :b RETURNING id"), {"b": b}
        )
        assert upd.all() == []
        assert dele.all() == []
    async with clinic_session(app_engine, b) as s:
        datos = (await s.execute(text("SELECT nombre FROM sala"))).scalars().all()
    assert datos == ["de-b"]


@pytest.mark.asyncio
async def test_sin_contexto_no_ve_nada(
    app_engine: AsyncEngine, clinicas: tuple[UUID, UUID]
) -> None:
    await _insertar(app_engine, clinicas[0], "algo")
    async with app_engine.connect() as c:
        salas = (await c.execute(text("SELECT count(*) FROM sala"))).scalar_one()
        cl = (await c.execute(text("SELECT count(*) FROM clinica"))).scalar_one()
    assert (salas, cl) == (0, 0)


@pytest.mark.asyncio
async def test_clinica_ve_solo_su_registro(
    app_engine: AsyncEngine, clinicas: tuple[UUID, UUID]
) -> None:
    a, _ = clinicas
    async with clinic_session(app_engine, a) as s:
        ids = (await s.execute(text("SELECT id FROM clinica"))).scalars().all()
    assert ids == [a]


@pytest.mark.asyncio
async def test_app_no_crea_clinicas(app_engine: AsyncEngine) -> None:
    with pytest.raises(DBAPIError):
        async with clinic_session(app_engine, uuid4()) as s:
            await s.execute(INSERTAR_CLINICA, {"id": uuid4(), "b": b"x"})


@pytest.mark.asyncio
async def test_app_no_es_dueno_ni_salta_rls(app_engine: AsyncEngine) -> None:
    async with app_engine.connect() as c:
        row = (
            await c.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            )
        ).one()
        dueno = (
            await c.execute(text("SELECT tableowner FROM pg_tables WHERE tablename = 'sala'"))
        ).scalar_one()
    assert tuple(row) == (False, False)
    assert dueno == "migrador"


@pytest.mark.asyncio
async def test_operador_no_accede_a_datos_de_clinica(operador_engine: AsyncEngine) -> None:
    for tabla in ("sala", "paciente", "evento_agenda", "personal"):
        with pytest.raises(DBAPIError):
            async with operador_engine.connect() as c:
                await c.execute(text(f"SELECT * FROM {tabla}"))  # noqa: S608
