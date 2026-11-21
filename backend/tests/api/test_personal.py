import os
from uuid import uuid4

import pyotp
import pytest
from app.auth.platform import PlatformCrypto
from app.crypto.keys import KeyProvider
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.testclient import TestClient

from .conftest import PASSWORD, como, crear_equipo, crear_invitacion_completa

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.environ.get("APP_TEST_DB") != "1",
        reason="Pruebas de BD: solo en CI (APP_TEST_DB=1)",
    ),
]

URL = "/api/personal"
INV = f"{URL}/invitaciones"


def _correo() -> str:
    return f"{uuid4().hex}@prueba.invalid"


async def test_listar_por_rol(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid, (admin, asis, med) = await crear_equipo(
        engine, platform, provider, "admin", "asistente", "medico"
    )
    await como(client, engine, platform, cid, admin)
    r = client.get(URL)
    assert r.status_code == 200
    assert {p["nombre"] for p in r.json()} == {"Persona 0", "Persona 1", "Persona 2"}
    await como(client, engine, platform, cid, asis)
    assert len(client.get(URL).json()) == 3
    await como(client, engine, platform, cid, med)
    assert [p["id"] for p in client.get(URL).json()] == [str(med.pid)]


@pytest.mark.parametrize(
    ("quien", "rol", "esperado"),
    [
        (0, "asistente", 201),
        (0, "medico", 201),
        (1, "medico", 201),
        (1, "asistente", 403),
        (2, "medico", 403),
        (0, "admin", 422),
    ],
)
async def test_invitar_por_rol(
    client: TestClient,
    engine: AsyncEngine,
    platform: PlatformCrypto,
    provider: KeyProvider,
    quien: int,
    rol: str,
    esperado: int,
) -> None:
    cid, equipo = await crear_equipo(engine, platform, provider, "admin", "asistente", "medico")
    h = await como(client, engine, platform, cid, equipo[quien])
    r = client.post(INV, json={"email": _correo(), "rol": rol}, headers=h)
    assert r.status_code == esperado


async def test_invitar_duplicado(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid, (admin, asis) = await crear_equipo(engine, platform, provider, "admin", "asistente")
    h = await como(client, engine, platform, cid, admin)
    correo = _correo()
    assert client.post(INV, json={"email": correo, "rol": "medico"}, headers=h).status_code == 201
    assert client.post(INV, json={"email": correo, "rol": "medico"}, headers=h).status_code == 409
    # Correo de alguien que ya es personal de la clínica.
    r = client.post(INV, json={"email": asis.email, "rol": "medico"}, headers=h)
    assert r.status_code == 409


async def test_tope_de_plan_cuenta_pendientes(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    """Plan p5: 3 médicos activos + 2 invitaciones pendientes de médico = tope."""
    cid, (admin, *_) = await crear_equipo(
        engine, platform, provider, "admin", "medico", "medico", "medico"
    )
    for _ in range(2):
        await crear_invitacion_completa(engine, platform, provider, rol="medico", clinica_id=cid)
    h = await como(client, engine, platform, cid, admin)
    assert (
        client.post(INV, json={"email": _correo(), "rol": "medico"}, headers=h).status_code == 409
    )
    # Los asistentes no cuentan para el plan.
    assert (
        client.post(INV, json={"email": _correo(), "rol": "asistente"}, headers=h).status_code
        == 201
    )


async def test_aviso_al_80_y_vencidas_no_cuentan(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid, (admin, *_) = await crear_equipo(
        engine, platform, provider, "admin", "medico", "medico", "medico"
    )
    await crear_invitacion_completa(
        engine, platform, provider, rol="medico", clinica_id=cid, horas=-1
    )
    h = await como(client, engine, platform, cid, admin)
    r = client.post(INV, json={"email": _correo(), "rol": "medico"}, headers=h)
    assert r.status_code == 201
    assert r.json()["medicos_usados"] == 4  # la vencida no cuenta
    assert r.json()["limite"] == 5
    assert r.json()["aviso"] is True

    cid2, (admin2,) = await crear_equipo(engine, platform, provider, "admin")
    h2 = await como(client, engine, platform, cid2, admin2)
    r2 = client.post(INV, json={"email": _correo(), "rol": "medico"}, headers=h2)
    assert r2.json()["aviso"] is False


async def test_invitacion_se_puede_activar(
    client: TestClient,
    otro_client: TestClient,
    engine: AsyncEngine,
    platform: PlatformCrypto,
    provider: KeyProvider,
) -> None:
    cid, (admin,) = await crear_equipo(engine, platform, provider, "admin")
    h = await como(client, engine, platform, cid, admin)
    token = client.post(INV, json={"email": _correo(), "rol": "medico"}, headers=h).json()["token"]
    ini = otro_client.post("/api/auth/activar/iniciar", json={"token": token, "password": PASSWORD})
    assert ini.status_code == 200
    ok = otro_client.post(
        "/api/auth/activar/confirmar",
        json={
            "token": token,
            "codigo": pyotp.TOTP(ini.json()["totp_secret"]).now(),
            "nombre": "Dra. Nueva",
        },
    )
    assert ok.status_code == 200
    roles = {p["nombre"]: p["rol"] for p in client.get(URL).json()}
    assert roles["Dra. Nueva"] == "medico"
    assert client.get(INV).json() == []  # ya no está pendiente


async def test_revocar_invitacion(
    client: TestClient,
    otro_client: TestClient,
    engine: AsyncEngine,
    platform: PlatformCrypto,
    provider: KeyProvider,
) -> None:
    cid, (admin, asis, med) = await crear_equipo(
        engine, platform, provider, "admin", "asistente", "medico"
    )
    h = await como(client, engine, platform, cid, admin)
    token = client.post(INV, json={"email": _correo(), "rol": "asistente"}, headers=h).json()[
        "token"
    ]
    iid = client.get(INV).json()[0]["id"]

    # El asistente no puede revocar la invitación de un asistente; el médico tampoco.
    h_asis = await como(otro_client, engine, platform, cid, asis)
    assert otro_client.post(f"{INV}/{iid}/revocar", headers=h_asis).status_code == 403
    h_med = await como(otro_client, engine, platform, cid, med)
    assert otro_client.post(f"{INV}/{iid}/revocar", headers=h_med).status_code == 403
    assert client.post(f"{INV}/{iid}/revocar", headers=h).status_code == 204

    r = otro_client.post("/api/auth/activar/iniciar", json={"token": token, "password": PASSWORD})
    assert r.status_code == 400


async def test_invitaciones_solo_admin_y_asistente(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid, (_, asis, med) = await crear_equipo(
        engine, platform, provider, "admin", "asistente", "medico"
    )
    await como(client, engine, platform, cid, asis)
    assert client.get(INV).status_code == 200
    await como(client, engine, platform, cid, med)
    assert client.get(INV).status_code == 403


async def test_idor_invitaciones(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid_a, (admin_a,) = await crear_equipo(engine, platform, provider, "admin")
    cid_b, (admin_b,) = await crear_equipo(engine, platform, provider, "admin")
    inv_a = await crear_invitacion_completa(
        engine, platform, provider, rol="asistente", clinica_id=cid_a
    )
    await crear_invitacion_completa(engine, platform, provider, rol="medico", clinica_id=cid_b)

    await como(client, engine, platform, cid_b, admin_b)
    id_b = client.get(INV).json()[0]["id"]

    h = await como(client, engine, platform, cid_a, admin_a)
    assert [i["email"] for i in client.get(INV).json()] == [inv_a.email]
    assert client.post(f"{INV}/{id_b}/revocar", headers=h).status_code == 404

    await como(client, engine, platform, cid_b, admin_b)
    assert [i["id"] for i in client.get(INV).json()] == [id_b]  # sigue vigente


async def test_idor_personal(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid_a, (admin_a,) = await crear_equipo(engine, platform, provider, "admin")
    cid_b, (admin_b, med_b) = await crear_equipo(engine, platform, provider, "admin", "medico")
    h = await como(client, engine, platform, cid_a, admin_a)
    assert client.post(f"{URL}/{med_b.pid}/desactivar", headers=h).status_code == 404
    assert client.post(f"{URL}/{med_b.pid}/reactivar", headers=h).status_code == 404
    r = client.patch(f"{URL}/{med_b.pid}", json={"nombre": "X"}, headers=h)
    assert r.status_code == 404
    assert str(med_b.pid) not in {p["id"] for p in client.get(URL).json()}

    await como(client, engine, platform, cid_b, admin_b)
    lista = {p["id"]: p for p in client.get(URL).json()}
    assert lista[str(med_b.pid)]["activo"] is True
    assert lista[str(med_b.pid)]["nombre"] == "Persona 1"  # no se editó


async def test_desactivar_corta_sesion_y_reactivar(
    client: TestClient,
    otro_client: TestClient,
    engine: AsyncEngine,
    platform: PlatformCrypto,
    provider: KeyProvider,
) -> None:
    cid, (admin, asis, med) = await crear_equipo(
        engine, platform, provider, "admin", "asistente", "medico"
    )
    await como(otro_client, engine, platform, cid, med)
    assert otro_client.get(URL).status_code == 200

    # El asistente no desactiva.
    h_asis = await como(client, engine, platform, cid, asis)
    assert client.post(f"{URL}/{med.pid}/desactivar", headers=h_asis).status_code == 403

    h = await como(client, engine, platform, cid, admin)
    assert client.post(f"{URL}/{admin.pid}/desactivar", headers=h).status_code == 409
    assert client.post(f"{URL}/{med.pid}/desactivar", headers=h).status_code == 204
    assert otro_client.get(URL).status_code == 401  # su sesión se cortó

    assert client.post(f"{URL}/{med.pid}/reactivar", headers=h).status_code == 204
    estado = {p["id"]: p["activo"] for p in client.get(URL).json()}
    assert estado[str(med.pid)] is True


async def test_reactivar_respeta_tope(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid, (admin, _, med2) = await crear_equipo(
        engine, platform, provider, "admin", "medico", "medico"
    )
    h = await como(client, engine, platform, cid, admin)
    assert client.post(f"{URL}/{med2.pid}/desactivar", headers=h).status_code == 204
    for _ in range(4):  # 1 médico activo + 4 pendientes = 5 (tope del plan p5)
        await crear_invitacion_completa(engine, platform, provider, rol="medico", clinica_id=cid)
    assert client.post(f"{URL}/{med2.pid}/reactivar", headers=h).status_code == 409


async def test_editar(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid, (admin, asis, med) = await crear_equipo(
        engine, platform, provider, "admin", "asistente", "medico"
    )
    h = await como(client, engine, platform, cid, med)
    r = client.patch(
        f"{URL}/{med.pid}",
        json={"nombre": "Dr. Nuevo", "contacto_preferido": "consultorio 3"},
        headers=h,
    )
    assert r.status_code == 200
    assert (r.json()["nombre"], r.json()["contacto_preferido"]) == ("Dr. Nuevo", "consultorio 3")
    assert client.patch(f"{URL}/{asis.pid}", json={"nombre": "X"}, headers=h).status_code == 403

    h = await como(client, engine, platform, cid, asis)
    assert client.patch(f"{URL}/{asis.pid}", json={}, headers=h).status_code == 422
    assert client.patch(f"{URL}/{asis.pid}", json={"nombre": "   "}, headers=h).status_code == 422
    r = client.patch(f"{URL}/{asis.pid}", json={"contacto_preferido": "x"}, headers=h)
    assert r.status_code == 422  # el contacto es solo de médicos

    h = await como(client, engine, platform, cid, admin)
    r = client.patch(f"{URL}/{asis.pid}", json={"nombre": "Otra"}, headers=h)
    assert r.status_code == 200
    assert r.json()["nombre"] == "Otra"
