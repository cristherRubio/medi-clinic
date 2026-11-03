"""Panel del operador, activación con clínica, invitaciones y contextos. Solo con APP_TEST_DB=1."""

import os
from typing import Any
from uuid import UUID, uuid4

import pyotp
import pytest
from app.auth.platform import PlatformCrypto
from app.crypto.keys import KeyProvider
from app.db.session import clinic_session
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.testclient import TestClient

from .conftest import PASSWORD, crear_invitacion_completa, crear_usuario

pytestmark = pytest.mark.skipif(
    os.environ.get("APP_TEST_DB") != "1", reason="Pruebas de BD: solo en CI (APP_TEST_DB=1)"
)

LOGIN = "/api/auth/login"
OP = "/api/operador"
INICIAR = "/api/auth/activar/iniciar"
CONFIRMAR = "/api/auth/activar/confirmar"
ACEPTAR = "/api/auth/activar/aceptar"


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["csrf"]}


async def _entrar_operador(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto
) -> None:
    c = await crear_usuario(engine, platform, totp=True, operador=True)
    assert c.totp_secret is not None
    client.post(LOGIN, json={"email": c.email, "password": PASSWORD})
    r = client.post(
        "/api/auth/login/totp",
        json={"codigo": pyotp.TOTP(c.totp_secret).now()},
        headers=_csrf(client),
    )
    assert r.status_code == 200


def _payload() -> dict[str, Any]:
    return {
        "nombre": "Clínica Prueba",
        "tipo_persona": "fisica",
        "nombre_legal": "Persona de Prueba",
        "rfc": "XAXX010101000",
        "representante_nombre": "Persona de Prueba",
        "representante_curp": "XEXX010101HNEXXXA4",
        "email_admin": f"{uuid4().hex}@prueba.invalid",
    }


def _crear(op: TestClient) -> tuple[dict[str, Any], str]:
    datos = _payload()
    r = op.post(f"{OP}/clinicas", json=datos, headers=_csrf(op))
    assert r.status_code == 201
    return r.json(), datos["email_admin"]


def _activar(cliente: TestClient, token: str, *, terminos: bool = True) -> tuple[int, list[str]]:
    r = cliente.post(INICIAR, json={"token": token, "password": PASSWORD})
    assert r.status_code == 200
    ok = cliente.post(
        CONFIRMAR,
        json={
            "token": token,
            "codigo": pyotp.TOTP(r.json()["totp_secret"]).now(),
            "nombre": "Dra Prueba",
            "acepta_terminos": terminos,
        },
    )
    return ok.status_code, ok.json().get("codigos_recuperacion", [])


@pytest.mark.asyncio
async def test_solo_el_operador_entra(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto
) -> None:
    assert client.get(f"{OP}/clinicas").status_code == 401
    c = await crear_usuario(engine, platform)
    client.post(LOGIN, json={"email": c.email, "password": PASSWORD})
    assert client.get(f"{OP}/clinicas").status_code == 404


@pytest.mark.asyncio
async def test_crear_clinica_y_activar_admin(
    client: TestClient,
    otro_client: TestClient,
    engine: AsyncEngine,
    platform: PlatformCrypto,
) -> None:
    await _entrar_operador(client, engine, platform)
    creada, _ = _crear(client)
    estado, _ = _activar(otro_client, creada["token"])
    assert estado == 200

    me = otro_client.get("/api/auth/me").json()
    assert me["clinica_id"] == creada["clinica_id"]
    async with clinic_session(engine, UUID(creada["clinica_id"])) as s:
        nombre = (await s.execute(text("SELECT nombre FROM personal"))).scalar_one()
        legales = (await s.execute(text("SELECT count(*) FROM aceptacion_legal"))).scalar_one()
    assert b"Dra Prueba" not in bytes(nombre)  # cifrado
    assert legales == 2  # términos + aviso


@pytest.mark.asyncio
async def test_admin_exige_aceptar_terminos(
    client: TestClient,
    otro_client: TestClient,
    engine: AsyncEngine,
    platform: PlatformCrypto,
) -> None:
    await _entrar_operador(client, engine, platform)
    creada, _ = _crear(client)
    estado, _ = _activar(otro_client, creada["token"], terminos=False)
    assert estado == 422


@pytest.mark.asyncio
async def test_revocar_y_extender_invitacion(
    client: TestClient,
    otro_client: TestClient,
    engine: AsyncEngine,
    platform: PlatformCrypto,
) -> None:
    await _entrar_operador(client, engine, platform)
    creada, _ = _crear(client)
    iid = creada["invitacion_id"]
    assert client.post(f"{OP}/invitaciones/{iid}/revocar", headers=_csrf(client)).status_code == 204
    r = otro_client.post(INICIAR, json={"token": creada["token"], "password": PASSWORD})
    assert r.status_code == 400
    ext = client.post(
        f"{OP}/invitaciones/{iid}/extender", json={"horas": 24}, headers=_csrf(client)
    )
    assert ext.status_code == 204
    r = otro_client.post(INICIAR, json={"token": creada["token"], "password": PASSWORD})
    assert r.status_code == 200
    # Las invitaciones de otra clínica no existen para este id.
    assert (
        client.post(f"{OP}/invitaciones/{uuid4()}/revocar", headers=_csrf(client)).status_code
        == 404
    )


@pytest.mark.asyncio
async def test_suspender_corta_sesiones_y_excluye_la_clinica(
    client: TestClient,
    otro_client: TestClient,
    engine: AsyncEngine,
    platform: PlatformCrypto,
) -> None:
    await _entrar_operador(client, engine, platform)
    creada, email_admin = _crear(client)
    estado, codigos = _activar(otro_client, creada["token"])
    assert estado == 200
    assert otro_client.get("/api/auth/me").status_code == 200

    r = client.patch(
        f"{OP}/clinicas/{creada['clinica_id']}",
        json={"estado": "suspendida"},
        headers=_csrf(client),
    )
    assert r.status_code == 200
    assert otro_client.get("/api/auth/me").status_code == 401  # sesión borrada en el acto

    otro_client.post(LOGIN, json={"email": email_admin, "password": PASSWORD})
    rec = otro_client.post(
        "/api/auth/login/recuperacion", json={"codigo": codigos[0]}, headers=_csrf(otro_client)
    )
    assert rec.status_code == 200
    assert otro_client.get("/api/auth/contextos").json() == []


@pytest.mark.asyncio
async def test_actualizar_clinica_valida(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto
) -> None:
    await _entrar_operador(client, engine, platform)
    creada, _ = _crear(client)
    url = f"{OP}/clinicas/{creada['clinica_id']}"
    assert client.patch(url, json={}, headers=_csrf(client)).status_code == 422
    assert client.patch(url, json={"plan": None}, headers=_csrf(client)).status_code == 422
    assert client.patch(url, json={"plan": "p99"}, headers=_csrf(client)).status_code == 422
    ok = client.patch(
        url, json={"plan": "p10", "notificaciones_whatsapp": True}, headers=_csrf(client)
    )
    assert ok.status_code == 200
    assert ok.json()["plan"] == "p10"
    assert ok.json()["notificaciones_whatsapp"] is True
    assert (
        client.patch(
            f"{OP}/clinicas/{uuid4()}", json={"plan": "p5"}, headers=_csrf(client)
        ).status_code
        == 404
    )


@pytest.mark.asyncio
async def test_usuario_existente_acepta_invitacion(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    c = await crear_usuario(engine, platform)
    inv = await crear_invitacion_completa(
        engine, platform, provider, rol="asistente", email=c.email
    )
    client.post(LOGIN, json={"email": c.email, "password": PASSWORD})
    cuerpo = {"token": inv.token, "nombre": "Asistente Prueba"}
    r = client.post(ACEPTAR, json=cuerpo, headers=_csrf(client))
    assert r.status_code == 200
    assert client.get("/api/auth/me").json()["clinica_id"] == str(inv.clinica_id)
    ctx = client.get("/api/auth/contextos").json()
    assert [x["rol"] for x in ctx] == ["asistente"]
    # Un solo uso.
    assert client.post(ACEPTAR, json=cuerpo, headers=_csrf(client)).status_code == 400


@pytest.mark.asyncio
async def test_no_se_acepta_invitacion_ajena(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    c = await crear_usuario(engine, platform)
    ajena = await crear_invitacion_completa(engine, platform, provider, rol="asistente")
    client.post(LOGIN, json={"email": c.email, "password": PASSWORD})
    r = client.post(ACEPTAR, json={"token": ajena.token, "nombre": "X"}, headers=_csrf(client))
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_aceptar_como_admin_exige_terminos(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    c = await crear_usuario(engine, platform)
    inv = await crear_invitacion_completa(engine, platform, provider, rol="admin", email=c.email)
    client.post(LOGIN, json={"email": c.email, "password": PASSWORD})
    r = client.post(ACEPTAR, json={"token": inv.token, "nombre": "X"}, headers=_csrf(client))
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_elegir_contexto_ajeno_es_404(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto
) -> None:
    c = await crear_usuario(engine, platform)
    client.post(LOGIN, json={"email": c.email, "password": PASSWORD})
    r = client.post("/api/auth/contexto", json={"personal_id": str(uuid4())}, headers=_csrf(client))
    assert r.status_code == 404
