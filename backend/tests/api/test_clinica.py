"""Configuración de la clínica: la ve todo el personal; la edita solo el admin."""

import os

import pytest
from app.auth import membership
from app.auth.platform import PlatformCrypto
from app.crypto.keys import KeyProvider
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from starlette.testclient import TestClient

from .conftest import como, crear_equipo

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.environ.get("APP_TEST_DB") != "1",
        reason="Pruebas de BD: solo en CI (APP_TEST_DB=1)",
    ),
]

URL = "/api/clinica"
HORARIO = {"lun": [["09:00", "14:00"], ["16:00", "20:00"]], "sab": [["09:00", "13:00"]]}


async def test_ver_todos_los_roles(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid, equipo = await crear_equipo(engine, platform, provider, "admin", "asistente", "medico")
    for m in equipo:
        await como(client, engine, platform, cid, m)
        r = client.get(URL)
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == str(cid)
        assert data["zona_horaria"] == "America/Mexico_City"
        assert data["horario_laboral"]["lun"] == []
        assert data["notificaciones_whatsapp"] is False


async def test_editar_solo_admin(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid, (admin, asis, med) = await crear_equipo(
        engine, platform, provider, "admin", "asistente", "medico"
    )
    for m in (asis, med):
        h = await como(client, engine, platform, cid, m)
        assert client.patch(URL, json={"nombre": "X"}, headers=h).status_code == 403
    h = await como(client, engine, platform, cid, admin)
    r = client.patch(
        URL,
        json={
            "nombre": "  Consultorio Prueba  ",
            "zona_horaria": "America/Tijuana",
            "google_maps_url": "https://maps.example.invalid/x",
            "politica_cancelacion": "Avisar con 24 h",
            "plantilla_recordatorio": "Recordatorio de cita",
            "horario_laboral": HORARIO,
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["nombre"] == "Consultorio Prueba"
    assert data["zona_horaria"] == "America/Tijuana"
    assert data["horario_laboral"]["lun"] == HORARIO["lun"]
    assert data["horario_laboral"]["dom"] == []
    # Borrar campos opcionales.
    r = client.patch(URL, json={"politica_cancelacion": "", "google_maps_url": None}, headers=h)
    assert r.json()["politica_cancelacion"] is None
    assert r.json()["google_maps_url"] is None
    assert r.json()["plantilla_recordatorio"] == "Recordatorio de cita"
    async with AsyncSession(engine) as s:
        await membership.fijar_contexto(s, cid)
        acciones = (
            await s.execute(
                text("SELECT accion FROM auditoria WHERE entidad = 'clinica' AND entidad_id = :c"),
                {"c": cid},
            )
        ).all()
    assert [a.accion for a in acciones] == ["clinica_configurada", "clinica_configurada"]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"nombre": "   "},
        {"nombre": None},
        {"zona_horaria": "Marte/Base"},
        {"zona_horaria": None},
        {"google_maps_url": "http://maps.example.invalid"},
        {"google_maps_url": "javascript:alert(1)"},
        {"horario_laboral": {"lun": [["09:00", "14:00"], ["13:00", "15:00"]]}},
        {"horario_laboral": None},
        {"politica_cancelacion": "x" * 501},
    ],
)
async def test_editar_invalido(
    client: TestClient,
    engine: AsyncEngine,
    platform: PlatformCrypto,
    provider: KeyProvider,
    body: dict[str, object],
) -> None:
    cid, (admin,) = await crear_equipo(engine, platform, provider, "admin")
    h = await como(client, engine, platform, cid, admin)
    assert client.patch(URL, json=body, headers=h).status_code == 422
