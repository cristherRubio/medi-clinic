"""Salas: roles, validación e IDOR entre clínicas. Solo con APP_TEST_DB=1."""

import os

import pytest
from app.auth.platform import PlatformCrypto
from app.crypto.keys import KeyProvider
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.testclient import TestClient

from .conftest import como, crear_equipo

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.environ.get("APP_TEST_DB") != "1",
        reason="Pruebas de BD: solo en CI (APP_TEST_DB=1)",
    ),
]

URL = "/api/salas"


async def test_salas_por_rol(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid, (admin, asis, med) = await crear_equipo(
        engine, platform, provider, "admin", "asistente", "medico"
    )
    h = await como(client, engine, platform, cid, admin)
    r = client.post(URL, json={"nombre": "Sala 1"}, headers=h)
    assert r.status_code == 201
    sid = r.json()["id"]

    for persona in (asis, med):  # todos ven; solo el admin gestiona
        h2 = await como(client, engine, platform, cid, persona)
        assert [s["id"] for s in client.get(URL).json()] == [sid]
        assert client.post(URL, json={"nombre": "X"}, headers=h2).status_code == 403
        assert client.patch(f"{URL}/{sid}", json={"activa": False}, headers=h2).status_code == 403

    h = await como(client, engine, platform, cid, admin)
    r = client.patch(f"{URL}/{sid}", json={"activa": False}, headers=h)
    assert r.status_code == 200
    assert r.json()["activa"] is False


async def test_salas_validacion(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid, (admin,) = await crear_equipo(engine, platform, provider, "admin")
    h = await como(client, engine, platform, cid, admin)
    sid = client.post(URL, json={"nombre": "Sala"}, headers=h).json()["id"]
    assert client.post(URL, json={"nombre": "   "}, headers=h).status_code == 422
    assert client.patch(f"{URL}/{sid}", json={"nombre": "   "}, headers=h).status_code == 422
    assert client.patch(f"{URL}/{sid}", json={}, headers=h).status_code == 422
    assert client.patch(f"{URL}/{sid}", json={"activa": None}, headers=h).status_code == 422


async def test_idor_salas(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid_a, (admin_a,) = await crear_equipo(engine, platform, provider, "admin")
    cid_b, (admin_b,) = await crear_equipo(engine, platform, provider, "admin")
    h_b = await como(client, engine, platform, cid_b, admin_b)
    id_b = client.post(URL, json={"nombre": "De B"}, headers=h_b).json()["id"]

    h_a = await como(client, engine, platform, cid_a, admin_a)
    assert client.get(URL).json() == []
    r = client.patch(f"{URL}/{id_b}", json={"nombre": "Robada"}, headers=h_a)
    assert r.status_code == 404

    await como(client, engine, platform, cid_b, admin_b)
    assert client.get(URL).json()[0]["nombre"] == "De B"
