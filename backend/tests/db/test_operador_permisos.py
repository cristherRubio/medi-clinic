"""El operador no ve datos de clínica ni tokens de sesión. Solo con APP_TEST_DB=1."""

import os
from uuid import uuid4

import pytest
from app.db.session import make_engine
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.skipif(
    os.environ.get("APP_TEST_DB") != "1", reason="Pruebas de BD: solo en CI (APP_TEST_DB=1)"
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM personal",
        "SELECT * FROM paciente",
        "SELECT * FROM evento_agenda",
        "SELECT * FROM sala",
        "SELECT token_hash FROM sesion",
        "SELECT usuario_id FROM sesion",
    ],
)
async def test_operador_sin_acceso(sql: str) -> None:
    e = make_engine("operador")
    try:
        with pytest.raises(DBAPIError):
            async with e.begin() as c:
                await c.execute(text(sql))
    finally:
        await e.dispose()


@pytest.mark.asyncio
async def test_operador_borra_sesiones_por_clinica() -> None:
    e = make_engine("operador")
    try:
        async with e.begin() as c:
            await c.execute(text("DELETE FROM sesion WHERE clinica_id = :c"), {"c": uuid4()})
    finally:
        await e.dispose()
