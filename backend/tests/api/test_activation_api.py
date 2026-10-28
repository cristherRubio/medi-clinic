"""Activación de invitación y códigos de recuperación. Solo con APP_TEST_DB=1."""

import os

import pyotp
import pytest
from app.auth.platform import PlatformCrypto
from app.auth.recovery import generate_recovery_codes, hash_code
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from starlette.testclient import TestClient

from .conftest import PASSWORD, crear_invitacion, crear_usuario

pytestmark = pytest.mark.skipif(
    os.environ.get("APP_TEST_DB") != "1", reason="Pruebas de BD: solo en CI (APP_TEST_DB=1)"
)

INICIAR = "/api/auth/activar/iniciar"
CONFIRMAR = "/api/auth/activar/confirmar"
LOGIN = "/api/auth/login"


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["csrf"]}


@pytest.mark.asyncio
async def test_activacion_completa(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto
) -> None:
    token, email = await crear_invitacion(engine, platform)
    r = client.post(INICIAR, json={"token": token, "password": PASSWORD})
    assert r.status_code == 200
    secreto = r.json()["totp_secret"]
    assert r.json()["otpauth_uri"].startswith("otpauth://totp/")

    # A medias no se puede entrar.
    assert client.post(LOGIN, json={"email": email, "password": PASSWORD}).status_code == 401

    ok = client.post(CONFIRMAR, json={"token": token, "codigo": pyotp.TOTP(secreto).now()})
    assert ok.status_code == 200
    codigos = ok.json()["codigos_recuperacion"]
    assert len(codigos) == 10
    assert client.get("/api/auth/me").json()["email"] == email

    # La invitación es de un solo uso.
    assert client.post(INICIAR, json={"token": token, "password": PASSWORD}).status_code == 400


@pytest.mark.asyncio
async def test_invitacion_invalida_o_vencida_es_uniforme(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto
) -> None:
    vencida, _ = await crear_invitacion(engine, platform, horas=-1)
    a = client.post(INICIAR, json={"token": vencida, "password": PASSWORD})
    b = client.post(INICIAR, json={"token": "x" * 43, "password": PASSWORD})
    assert a.status_code == b.status_code == 400
    assert a.json() == b.json()


@pytest.mark.asyncio
async def test_codigo_malo_no_consume_la_invitacion(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto
) -> None:
    token, _ = await crear_invitacion(engine, platform)
    secreto = client.post(INICIAR, json={"token": token, "password": PASSWORD}).json()[
        "totp_secret"
    ]
    mal = client.post(CONFIRMAR, json={"token": token, "codigo": "000000"})
    assert mal.status_code == 400
    bien = client.post(CONFIRMAR, json={"token": token, "codigo": pyotp.TOTP(secreto).now()})
    assert bien.status_code == 200


@pytest.mark.asyncio
async def test_politica_de_contrasena(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto
) -> None:
    token, _ = await crear_invitacion(engine, platform)
    assert client.post(INICIAR, json={"token": token, "password": "corta"}).status_code == 422


@pytest.mark.asyncio
async def test_login_con_codigo_de_recuperacion_un_solo_uso(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto
) -> None:
    c = await crear_usuario(engine, platform, totp=True)
    codigos = generate_recovery_codes()
    async with AsyncSession(engine) as s:
        for cod in codigos:
            await s.execute(
                text("INSERT INTO codigo_recuperacion (usuario_id, codigo_hash) VALUES (:u, :h)"),
                {"u": c.id, "h": hash_code(cod)},
            )
        await s.commit()

    client.post(LOGIN, json={"email": c.email, "password": PASSWORD})
    ok = client.post(
        "/api/auth/login/recuperacion", json={"codigo": codigos[0]}, headers=_csrf(client)
    )
    assert ok.status_code == 200
    assert client.get("/api/auth/me").status_code == 200

    client.post("/api/auth/logout", headers=_csrf(client))
    client.post(LOGIN, json={"email": c.email, "password": PASSWORD})
    rep = client.post(
        "/api/auth/login/recuperacion", json={"codigo": codigos[0]}, headers=_csrf(client)
    )
    assert rep.status_code == 401
