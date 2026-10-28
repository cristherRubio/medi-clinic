"""Login, 2FA, CSRF y bloqueo de punta a punta. Solo con APP_TEST_DB=1."""

import os

import pyotp
import pytest
from app.auth.platform import PlatformCrypto
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.testclient import TestClient

from .conftest import PASSWORD, crear_usuario

pytestmark = pytest.mark.skipif(
    os.environ.get("APP_TEST_DB") != "1", reason="Pruebas de BD: solo en CI (APP_TEST_DB=1)"
)

LOGIN = "/api/auth/login"


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["csrf"]}


@pytest.mark.asyncio
async def test_login_sin_2fa_y_me(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto
) -> None:
    c = await crear_usuario(engine, platform)
    r = client.post(LOGIN, json={"email": c.email, "password": PASSWORD})
    assert r.status_code == 200
    assert r.json() == {"mfa_requerida": False}
    assert "httponly" in r.headers["set-cookie"].lower()
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == c.email
    assert me.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_credenciales_uniformes(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto
) -> None:
    c = await crear_usuario(engine, platform)
    mala = client.post(LOGIN, json={"email": c.email, "password": "otra-clave-larga-x"})
    ajena = client.post(LOGIN, json={"email": "nadie@prueba.invalid", "password": PASSWORD})
    assert mala.status_code == ajena.status_code == 401
    assert mala.json() == ajena.json()


@pytest.mark.asyncio
async def test_flujo_2fa_csrf_y_reuso(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto
) -> None:
    c = await crear_usuario(engine, platform, totp=True)
    assert c.totp_secret is not None
    codigo = pyotp.TOTP(c.totp_secret).now()

    r = client.post(LOGIN, json={"email": c.email, "password": PASSWORD})
    assert r.json() == {"mfa_requerida": True}
    assert client.get("/api/auth/me").status_code == 401  # sesión intermedia
    assert (
        client.post("/api/auth/login/totp", json={"codigo": codigo}).status_code == 403
    )  # sin CSRF
    ok = client.post("/api/auth/login/totp", json={"codigo": codigo}, headers=_csrf(client))
    assert ok.status_code == 200
    assert client.get("/api/auth/me").status_code == 200

    # El mismo código no sirve una segunda vez.
    assert client.post("/api/auth/logout", headers=_csrf(client)).status_code == 204
    client.post(LOGIN, json={"email": c.email, "password": PASSWORD})
    rep = client.post("/api/auth/login/totp", json={"codigo": codigo}, headers=_csrf(client))
    assert rep.status_code == 401


@pytest.mark.asyncio
async def test_bloqueo_por_cuenta(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto
) -> None:
    c = await crear_usuario(engine, platform)
    for _ in range(5):
        r = client.post(LOGIN, json={"email": c.email, "password": "otra-clave-larga-x"})
        assert r.status_code == 401
    bien = client.post(LOGIN, json={"email": c.email, "password": PASSWORD})
    assert bien.status_code == 429


@pytest.mark.asyncio
async def test_logout_exige_csrf(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto
) -> None:
    c = await crear_usuario(engine, platform)
    client.post(LOGIN, json={"email": c.email, "password": PASSWORD})
    assert client.post("/api/auth/logout").status_code == 403
    assert client.post("/api/auth/logout", headers=_csrf(client)).status_code == 204
    assert client.get("/api/auth/me").status_code == 401


@pytest.mark.asyncio
async def test_operador_sin_2fa_no_entra(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto
) -> None:
    c = await crear_usuario(engine, platform, operador=True)
    r = client.post(LOGIN, json={"email": c.email, "password": PASSWORD})
    assert r.status_code == 401
