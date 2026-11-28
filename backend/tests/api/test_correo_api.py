"""Invitaciones por correo, reenvío y restablecimiento de contraseña."""

import os
import re
from uuid import uuid4

import pyotp
import pytest
from app.auth.platform import PlatformCrypto
from app.auth.recovery import generate_recovery_codes, hash_code
from app.crypto.keys import KeyProvider
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from starlette.testclient import TestClient

from .conftest import (
    PASSWORD,
    MemoriaCorreo,
    _cliente,
    como,
    crear_equipo,
    crear_usuario,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.environ.get("APP_TEST_DB") != "1",
        reason="Pruebas de BD: solo en CI (APP_TEST_DB=1)",
    ),
]

OLVIDE = "/api/auth/contrasena/olvide"
RESTABLECER = "/api/auth/contrasena/restablecer"
INICIAR = "/api/auth/activar/iniciar"
LOGIN = "/api/auth/login"
NUEVA = "otra-clave-nueva-larga"


def _correo() -> str:
    return f"{uuid4().hex}@prueba.invalid"


def _token(texto: str, ruta: str) -> str:
    m = re.search(rf"/{ruta}#t=(\S+)", texto)
    assert m is not None
    return m.group(1)


def _csrf(c: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": c.cookies["csrf"]}


# --- Invitaciones --------------------------------------------------------------------------


async def test_invitacion_por_correo(
    client_correo: TestClient,
    correo: MemoriaCorreo,
    engine: AsyncEngine,
    platform: PlatformCrypto,
    provider: KeyProvider,
) -> None:
    cid, (admin,) = await crear_equipo(engine, platform, provider, "admin")
    h = await como(client_correo, engine, platform, cid, admin)
    destino = _correo()
    r = client_correo.post(
        "/api/personal/invitaciones", json={"email": destino, "rol": "medico"}, headers=h
    )
    assert r.status_code == 201
    assert r.json()["correo_enviado"] is True
    assert r.json()["token"] is None  # ya no se devuelve
    (enviado,) = correo.enviados
    assert enviado.para == destino
    assert "test" in enviado.asunto  # nombre de la clínica de prueba
    token = _token(enviado.texto, "activar")
    assert (
        client_correo.post(INICIAR, json={"token": token, "password": PASSWORD}).status_code == 200
    )


async def test_fallo_del_correo_deshace_la_invitacion(
    platform: PlatformCrypto, provider: KeyProvider, engine: AsyncEngine
) -> None:
    falla = MemoriaCorreo(falla=True)
    cid, (admin,) = await crear_equipo(engine, platform, provider, "admin")
    for c in _cliente(platform, provider, falla):
        h = await como(c, engine, platform, cid, admin)
        r = c.post(
            "/api/personal/invitaciones", json={"email": _correo(), "rol": "medico"}, headers=h
        )
        assert r.status_code == 502
        assert c.get("/api/personal/invitaciones").json() == []


async def test_reenviar_invitacion_sin_correo(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid, (admin, asis) = await crear_equipo(engine, platform, provider, "admin", "asistente")
    h = await como(client, engine, platform, cid, admin)
    r = client.post(
        "/api/personal/invitaciones", json={"email": _correo(), "rol": "asistente"}, headers=h
    )
    assert r.json()["correo_enviado"] is False
    iid, viejo = r.json()["invitacion_id"], r.json()["token"]
    r = client.post(f"/api/personal/invitaciones/{iid}/reenviar", headers=h)
    assert r.status_code == 200
    nuevo = r.json()["token"]
    assert nuevo
    assert nuevo != viejo
    assert client.post(INICIAR, json={"token": viejo, "password": PASSWORD}).status_code == 400
    # El asistente no reenvía invitaciones de asistente; otra clínica no la encuentra.
    h = await como(client, engine, platform, cid, asis)
    assert client.post(f"/api/personal/invitaciones/{iid}/reenviar", headers=h).status_code == 403
    cid2, (admin2,) = await crear_equipo(engine, platform, provider, "admin")
    h = await como(client, engine, platform, cid2, admin2)
    assert client.post(f"/api/personal/invitaciones/{iid}/reenviar", headers=h).status_code == 404
    assert client.post(INICIAR, json={"token": nuevo, "password": PASSWORD}).status_code == 200


async def test_operador_invita_y_reenvia_por_correo(
    client_correo: TestClient, correo: MemoriaCorreo, engine: AsyncEngine, platform: PlatformCrypto
) -> None:
    op = await crear_usuario(engine, platform, totp=True, operador=True)
    assert op.totp_secret is not None
    client_correo.post(LOGIN, json={"email": op.email, "password": PASSWORD})
    client_correo.post(
        "/api/auth/login/totp",
        json={"codigo": pyotp.TOTP(op.totp_secret).now()},
        headers=_csrf(client_correo),
    )
    destino = _correo()
    r = client_correo.post(
        "/api/operador/clinicas",
        json={
            "nombre": "Clínica Correo",
            "tipo_persona": "fisica",
            "nombre_legal": "Persona de Prueba",
            "rfc": "XAXX010101000",
            "representante_nombre": "Persona de Prueba",
            "representante_curp": "XEXX010101HNEXXXA4",
            "email_admin": destino,
        },
        headers=_csrf(client_correo),
    )
    assert r.status_code == 201
    assert (r.json()["token"], r.json()["correo_enviado"]) == (None, True)
    iid = r.json()["invitacion_id"]
    r = client_correo.post(
        f"/api/operador/invitaciones/{iid}/reenviar", headers=_csrf(client_correo)
    )
    assert r.status_code == 200
    primero, segundo = correo.enviados
    assert primero.para == segundo.para == destino
    assert "Clínica Correo" in primero.asunto
    assert "como administrador(a)" in segundo.texto
    assert _token(primero.texto, "activar") != _token(segundo.texto, "activar")


# --- Restablecimiento de contraseña --------------------------------------------------------


async def test_restablecer_sin_totp(
    client_correo: TestClient,
    otro_client: TestClient,
    correo: MemoriaCorreo,
    engine: AsyncEngine,
    platform: PlatformCrypto,
) -> None:
    u = await crear_usuario(engine, platform)
    assert otro_client.post(LOGIN, json={"email": u.email, "password": PASSWORD}).status_code == 200
    r = client_correo.post(OLVIDE, json={"email": u.email})
    assert r.status_code == 202
    (enviado,) = correo.enviados
    assert enviado.para == u.email
    token = _token(enviado.texto, "restablecer")

    assert (
        client_correo.post(RESTABLECER, json={"token": token, "password": "corta"}).status_code
        == 422
    )
    r = client_correo.post(RESTABLECER, json={"token": token, "password": NUEVA})
    assert r.status_code == 204
    assert otro_client.get("/api/auth/me").status_code == 401  # sesiones cerradas
    assert (
        client_correo.post(LOGIN, json={"email": u.email, "password": PASSWORD}).status_code == 401
    )
    assert client_correo.post(LOGIN, json={"email": u.email, "password": NUEVA}).status_code == 200
    # Un solo uso.
    assert (
        client_correo.post(RESTABLECER, json={"token": token, "password": NUEVA}).status_code == 400
    )


async def test_olvide_no_revela_si_la_cuenta_existe(
    client_correo: TestClient,
    client: TestClient,
    correo: MemoriaCorreo,
    engine: AsyncEngine,
    platform: PlatformCrypto,
) -> None:
    u = await crear_usuario(engine, platform)
    existe = client_correo.post(OLVIDE, json={"email": u.email})
    no_existe = client_correo.post(OLVIDE, json={"email": _correo()})
    assert existe.status_code == no_existe.status_code == 202
    assert existe.json() == no_existe.json()
    assert [c.para for c in correo.enviados] == [u.email]
    # Sin proveedor de correo: misma respuesta y no se crea ningún token.
    sin = client.post(OLVIDE, json={"email": u.email})
    assert (sin.status_code, sin.json()) == (202, existe.json())
    async with AsyncSession(engine) as s:
        n = (
            await s.execute(
                text("SELECT count(*) FROM restablecimiento WHERE usuario_id = :u"), {"u": u.id}
            )
        ).scalar_one()
    assert n == 1


async def test_limite_por_cuenta_y_token_nuevo_invalida_el_anterior(
    client_correo: TestClient, correo: MemoriaCorreo, engine: AsyncEngine, platform: PlatformCrypto
) -> None:
    u = await crear_usuario(engine, platform)
    for _ in range(5):
        assert client_correo.post(OLVIDE, json={"email": u.email}).status_code == 202
    assert len(correo.enviados) == 3  # el resto, 202 sin correo
    primero, _, ultimo = (_token(c.texto, "restablecer") for c in correo.enviados)
    assert (
        client_correo.post(RESTABLECER, json={"token": primero, "password": NUEVA}).status_code
        == 400
    )
    assert (
        client_correo.post(RESTABLECER, json={"token": ultimo, "password": NUEVA}).status_code
        == 204
    )


async def test_restablecer_con_totp_exige_codigo(
    client_correo: TestClient, correo: MemoriaCorreo, engine: AsyncEngine, platform: PlatformCrypto
) -> None:
    u = await crear_usuario(engine, platform, totp=True)
    assert u.totp_secret is not None
    client_correo.post(OLVIDE, json={"email": u.email})
    token = _token(correo.enviados[0].texto, "restablecer")
    cuerpo = {"token": token, "password": NUEVA}
    assert client_correo.post(RESTABLECER, json=cuerpo).status_code == 422
    assert client_correo.post(RESTABLECER, json={**cuerpo, "codigo": "000000"}).status_code == 400
    r = client_correo.post(RESTABLECER, json={**cuerpo, "codigo": pyotp.TOTP(u.totp_secret).now()})
    assert r.status_code == 204


async def test_restablecer_con_codigo_de_recuperacion_y_bloqueo(
    client_correo: TestClient, correo: MemoriaCorreo, engine: AsyncEngine, platform: PlatformCrypto
) -> None:
    u = await crear_usuario(engine, platform, totp=True)
    codigos = generate_recovery_codes()
    async with AsyncSession(engine) as s:
        await s.execute(
            text("INSERT INTO codigo_recuperacion (usuario_id, codigo_hash) VALUES (:u, :h)"),
            {"u": u.id, "h": hash_code(codigos[0])},
        )
        await s.commit()
    client_correo.post(OLVIDE, json={"email": u.email})
    token = _token(correo.enviados[0].texto, "restablecer")
    cuerpo = {"token": token, "password": NUEVA}
    for _ in range(5):
        assert client_correo.post(RESTABLECER, json={**cuerpo, "codigo": "malo"}).status_code == 400
    # Tras 5 códigos malos el enlace queda bloqueado un rato, aunque el código sea bueno.
    assert client_correo.post(RESTABLECER, json={**cuerpo, "codigo": codigos[0]}).status_code == 429

    client_correo.post(OLVIDE, json={"email": u.email})
    token = _token(correo.enviados[1].texto, "restablecer")
    r = client_correo.post(
        RESTABLECER, json={"token": token, "password": NUEVA, "codigo": codigos[0]}
    )
    assert r.status_code == 204


async def test_enlace_vencido(
    client_correo: TestClient, correo: MemoriaCorreo, engine: AsyncEngine, platform: PlatformCrypto
) -> None:
    u = await crear_usuario(engine, platform)
    client_correo.post(OLVIDE, json={"email": u.email})
    token = _token(correo.enviados[0].texto, "restablecer")
    async with AsyncSession(engine) as s:
        await s.execute(
            text(
                "UPDATE restablecimiento SET expira_en = now() - interval '1 minute' "
                "WHERE usuario_id = :u"
            ),
            {"u": u.id},
        )
        await s.commit()
    r = client_correo.post(RESTABLECER, json={"token": token, "password": NUEVA})
    assert r.status_code == 400
    assert (
        client_correo.post(LOGIN, json={"email": u.email, "password": PASSWORD}).status_code == 200
    )
