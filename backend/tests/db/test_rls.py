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

INSERTAR = text("INSERT INTO _rls_demo (clinica_id, dato) VALUES (:c, :d)")


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


async def _insertar(engine: AsyncEngine, clinica: UUID, dato: str) -> None:
    async with clinic_session(engine, clinica) as s:
        await s.execute(INSERTAR, {"c": clinica, "d": dato})


@pytest.mark.asyncio
async def test_cada_clinica_ve_solo_lo_suyo(app_engine: AsyncEngine) -> None:
    a, b = uuid4(), uuid4()
    await _insertar(app_engine, a, "de-a")
    await _insertar(app_engine, b, "de-b")
    async with clinic_session(app_engine, a) as s:
        datos = (await s.execute(text("SELECT dato FROM _rls_demo"))).scalars().all()
    assert datos == ["de-a"]


@pytest.mark.asyncio
async def test_no_puede_insertar_en_otra_clinica(app_engine: AsyncEngine) -> None:
    a, b = uuid4(), uuid4()
    with pytest.raises(DBAPIError):
        await _insertar_ajeno(app_engine, contexto=a, destino=b)


async def _insertar_ajeno(engine: AsyncEngine, contexto: UUID, destino: UUID) -> None:
    async with clinic_session(engine, contexto) as s:
        await s.execute(INSERTAR, {"c": destino, "d": "intruso"})


@pytest.mark.asyncio
async def test_no_modifica_ni_borra_filas_ajenas(app_engine: AsyncEngine) -> None:
    a, b = uuid4(), uuid4()
    await _insertar(app_engine, b, "de-b")
    async with clinic_session(app_engine, a) as s:
        upd = await s.execute(
            text("UPDATE _rls_demo SET dato = 'x' WHERE clinica_id = :b RETURNING id"), {"b": b}
        )
        dele = await s.execute(
            text("DELETE FROM _rls_demo WHERE clinica_id = :b RETURNING id"), {"b": b}
        )
        assert upd.all() == []
        assert dele.all() == []
    async with clinic_session(app_engine, b) as s:
        datos = (await s.execute(text("SELECT dato FROM _rls_demo"))).scalars().all()
    assert datos == ["de-b"]


@pytest.mark.asyncio
async def test_sin_contexto_no_ve_nada(app_engine: AsyncEngine) -> None:
    await _insertar(app_engine, uuid4(), "algo")
    async with app_engine.connect() as c:
        total = (await c.execute(text("SELECT count(*) FROM _rls_demo"))).scalar_one()
    assert total == 0


@pytest.mark.asyncio
async def test_app_no_es_dueno_ni_salta_rls(app_engine: AsyncEngine) -> None:
    async with app_engine.connect() as c:
        row = (
            await c.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            )
        ).one()
        dueno = (
            await c.execute(text("SELECT tableowner FROM pg_tables WHERE tablename = '_rls_demo'"))
        ).scalar_one()
    assert tuple(row) == (False, False)
    assert dueno == "migrador"


@pytest.mark.asyncio
async def test_operador_no_accede_a_la_tabla(operador_engine: AsyncEngine) -> None:
    with pytest.raises(DBAPIError):
        async with operador_engine.connect() as c:
            await c.execute(text("SELECT * FROM _rls_demo"))
