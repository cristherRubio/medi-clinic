"""Cada ruta que modifica registra su acción de auditoría (tabla en test_auditoria_cobertura),
los 403 quedan registrados y ni la auditoría ni los logs llevan datos personales."""

import logging
import os
from typing import Any
from uuid import UUID, uuid4

import pyotp
import pytest
from app.auth import membership
from app.auth.platform import PlatformCrypto
from app.auth.recovery import generate_recovery_codes, hash_code
from app.crypto.keys import KeyProvider
from app.db.session import make_engine
from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from starlette.testclient import TestClient

from test_auditoria_cobertura import GRUPOS, Ruta

from .conftest import (
    PASSWORD,
    como,
    crear_equipo,
    crear_invitacion_completa,
    crear_personal,
    crear_usuario,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.environ.get("APP_TEST_DB") != "1",
        reason="Pruebas de BD: solo en CI (APP_TEST_DB=1)",
    ),
]

LOGIN = "/api/auth/login"
_SIN_COMPROBAR = object()


def _csrf(c: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": c.cookies["csrf"]}


async def _registros(
    accion: str | None = None, *, actor: UUID | None = None, entidad_id: Any = None
) -> list[Row[Any]]:
    """Lee `auditoria` como `migrador` (único rol que ve también los eventos sin clínica)."""
    assert actor is not None or entidad_id is not None  # no mezclar filas de otras pruebas
    e = make_engine("migrador")
    try:
        async with AsyncSession(e) as s:
            return list(
                (
                    await s.execute(
                        text(
                            "SELECT accion, actor_usuario_id, clinica_id, entidad, entidad_id, "
                            "ip, metadata FROM auditoria "
                            "WHERE (CAST(:a AS text) IS NULL OR accion = CAST(:a AS text)) "
                            "AND (CAST(:u AS uuid) IS NULL OR actor_usuario_id = CAST(:u AS uuid)) "
                            "AND (CAST(:e AS uuid) IS NULL OR entidad_id = CAST(:e AS uuid)) "
                            "ORDER BY creado_en DESC"
                        ),
                        {"a": accion, "u": actor, "e": entidad_id},
                    )
                ).all()
            )
    finally:
        await e.dispose()


class Cobertura:
    """Comprueba la acción esperada de cada ruta de un grupo y que no falte ninguna."""

    def __init__(self, grupo: str) -> None:
        self.esperadas = GRUPOS[grupo]
        self.vistas: set[Ruta] = set()

    async def ver(
        self,
        metodo: str,
        ruta: str,
        *,
        actor: UUID,
        entidad_id: Any = None,
        clinica_id: Any = _SIN_COMPROBAR,
    ) -> dict[str, Any]:
        accion = self.esperadas[(metodo, ruta)]
        filas = await _registros(accion, actor=actor, entidad_id=entidad_id)
        assert filas, f"{metodo} {ruta}: falta el registro {accion}"
        fila = filas[0]
        if clinica_id is not _SIN_COMPROBAR:
            assert fila.clinica_id == clinica_id, f"{metodo} {ruta}: clínica equivocada"
        self.vistas.add((metodo, ruta))
        meta: dict[str, Any] = fila.metadata
        return meta

    def completa(self) -> None:
        assert self.vistas == set(self.esperadas)


async def _entrar_operador(c: TestClient, engine: AsyncEngine, platform: PlatformCrypto) -> UUID:
    op = await crear_usuario(engine, platform, totp=True, operador=True)
    assert op.totp_secret is not None
    c.post(LOGIN, json={"email": op.email, "password": PASSWORD})
    r = c.post(
        "/api/auth/login/totp", json={"codigo": pyotp.TOTP(op.totp_secret).now()}, headers=_csrf(c)
    )
    assert r.status_code == 200
    return op.id


async def test_auditoria_auth(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cob = Cobertura("auth")
    cid, (admin,) = await crear_equipo(engine, platform, provider, "admin")
    # Login sin 2FA, elegir clínica, logout.
    assert client.post(LOGIN, json={"email": admin.email, "password": PASSWORD}).status_code == 200
    await cob.ver("POST", LOGIN, actor=admin.uid, clinica_id=None)
    r = client.post(
        "/api/auth/contexto", json={"personal_id": str(admin.pid)}, headers=_csrf(client)
    )
    assert r.status_code == 200
    await cob.ver(
        "POST", "/api/auth/contexto", actor=admin.uid, entidad_id=admin.pid, clinica_id=cid
    )
    assert client.post("/api/auth/logout", headers=_csrf(client)).status_code == 204
    await cob.ver("POST", "/api/auth/logout", actor=admin.uid)
    # Fallo de contraseña.
    client.post(LOGIN, json={"email": admin.email, "password": "otra-clave-larga-x"})
    assert await _registros("login_fallido", actor=admin.uid)

    # Con TOTP.
    t = await crear_usuario(engine, platform, totp=True)
    assert t.totp_secret is not None
    client.post(LOGIN, json={"email": t.email, "password": PASSWORD})
    assert await _registros("login_password_ok", actor=t.id)
    r = client.post(
        "/api/auth/login/totp",
        json={"codigo": pyotp.TOTP(t.totp_secret).now()},
        headers=_csrf(client),
    )
    assert r.status_code == 200
    meta = await cob.ver("POST", "/api/auth/login/totp", actor=t.id)
    assert meta == {"metodo": "totp"}
    client.post("/api/auth/logout", headers=_csrf(client))

    # Con código de recuperación.
    rc = await crear_usuario(engine, platform, totp=True)
    codigos = generate_recovery_codes()
    async with AsyncSession(engine) as s:
        await s.execute(
            text("INSERT INTO codigo_recuperacion (usuario_id, codigo_hash) VALUES (:u, :h)"),
            {"u": rc.id, "h": hash_code(codigos[0])},
        )
        await s.commit()
    client.post(LOGIN, json={"email": rc.email, "password": PASSWORD})
    r = client.post(
        "/api/auth/login/recuperacion", json={"codigo": "x" * 10}, headers=_csrf(client)
    )
    assert r.status_code == 401
    assert await _registros("login_recuperacion_fallido", actor=rc.id)
    r = client.post(
        "/api/auth/login/recuperacion", json={"codigo": codigos[0]}, headers=_csrf(client)
    )
    assert r.status_code == 200
    meta = await cob.ver("POST", "/api/auth/login/recuperacion", actor=rc.id)
    assert meta == {"metodo": "recuperacion"}
    cob.completa()


async def test_auditoria_activacion(
    client: TestClient,
    otro_client: TestClient,
    engine: AsyncEngine,
    platform: PlatformCrypto,
    provider: KeyProvider,
) -> None:
    cob = Cobertura("activacion")
    inv = await crear_invitacion_completa(engine, platform, provider)
    r = client.post("/api/auth/activar/iniciar", json={"token": inv.token, "password": PASSWORD})
    assert r.status_code == 200
    secreto = r.json()["totp_secret"]
    r = client.post(
        "/api/auth/activar/confirmar",
        json={
            "token": inv.token,
            "codigo": pyotp.TOTP(secreto).now(),
            "nombre": "Admin Prueba",
            "acepta_terminos": True,
        },
    )
    assert r.status_code == 200
    uid = UUID(client.get("/api/auth/me").json()["id"])
    await cob.ver("POST", "/api/auth/activar/iniciar", actor=uid, entidad_id=uid)
    meta = await cob.ver("POST", "/api/auth/activar/confirmar", actor=uid, entidad_id=uid)
    assert meta == {"rol": "admin"}
    # Invitación inválida: fallo sin actor (no se sabe quién es).
    r = client.post("/api/auth/activar/iniciar", json={"token": inv.token, "password": PASSWORD})
    assert r.status_code == 400

    # Usuario existente que acepta otra invitación.
    u = await crear_usuario(engine, platform)
    inv2 = await crear_invitacion_completa(
        engine, platform, provider, rol="medico", email=u.email, clinica_id=inv.clinica_id
    )
    otro_client.post(LOGIN, json={"email": u.email, "password": PASSWORD})
    r = otro_client.post(
        "/api/auth/activar/aceptar",
        json={"token": inv2.token, "nombre": "Medico Prueba"},
        headers=_csrf(otro_client),
    )
    assert r.status_code == 200
    pid = UUID(r.json()["personal_id"])
    await cob.ver(
        "POST", "/api/auth/activar/aceptar", actor=u.id, entidad_id=pid, clinica_id=inv.clinica_id
    )
    cob.completa()


async def test_auditoria_operador(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto
) -> None:
    cob = Cobertura("operador")
    op = await _entrar_operador(client, engine, platform)
    h = _csrf(client)
    r = client.post(
        "/api/operador/clinicas",
        json={
            "nombre": "Clínica Prueba",
            "tipo_persona": "fisica",
            "nombre_legal": "Persona de Prueba",
            "rfc": "XAXX010101000",
            "representante_nombre": "Persona de Prueba",
            "representante_curp": "XEXX010101HNEXXXA4",
            "email_admin": f"{uuid4().hex}@prueba.invalid",
        },
        headers=h,
    )
    assert r.status_code == 201
    cid, iid = UUID(r.json()["clinica_id"]), UUID(r.json()["invitacion_id"])
    await cob.ver("POST", "/api/operador/clinicas", actor=op, entidad_id=cid, clinica_id=cid)
    r = client.patch(f"/api/operador/clinicas/{cid}", json={"plan": "p10"}, headers=h)
    assert r.status_code == 200
    await cob.ver(
        "PATCH", "/api/operador/clinicas/{clinica_id}", actor=op, entidad_id=cid, clinica_id=cid
    )
    r = client.post(f"/api/operador/invitaciones/{iid}/extender", json={"horas": 24}, headers=h)
    assert r.status_code == 204
    await cob.ver(
        "POST",
        "/api/operador/invitaciones/{invitacion_id}/extender",
        actor=op,
        entidad_id=iid,
        clinica_id=cid,
    )
    assert client.post(f"/api/operador/invitaciones/{iid}/revocar", headers=h).status_code == 204
    await cob.ver(
        "POST",
        "/api/operador/invitaciones/{invitacion_id}/revocar",
        actor=op,
        entidad_id=iid,
        clinica_id=cid,
    )
    cob.completa()


async def test_auditoria_recursos_de_clinica(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cob = Cobertura("clinica")
    cid, (admin, med, med2) = await crear_equipo(
        engine, platform, provider, "admin", "medico", "medico"
    )
    h = await como(client, engine, platform, cid, admin)

    async def ver(metodo: str, ruta: str, entidad_id: Any) -> dict[str, Any]:
        return await cob.ver(metodo, ruta, actor=admin.uid, entidad_id=entidad_id, clinica_id=cid)

    def ok(r: Any) -> Any:
        assert r.status_code < 300, r.text
        return r.json() if r.content else None

    ok(client.patch("/api/clinica", json={"nombre": "Otro nombre"}, headers=h))
    assert await ver("PATCH", "/api/clinica", cid) == {"campos": ["nombre"]}

    sala = ok(client.post("/api/salas", json={"nombre": "S1"}, headers=h))["id"]
    await ver("POST", "/api/salas", sala)
    ok(client.patch(f"/api/salas/{sala}", json={"nombre": "S2"}, headers=h))
    await ver("PATCH", "/api/salas/{sala_id}", sala)

    ok(client.patch(f"/api/personal/{med.pid}", json={"nombre": "Nuevo"}, headers=h))
    await ver("PATCH", "/api/personal/{personal_id}", med.pid)
    ok(client.post(f"/api/personal/{med2.pid}/desactivar", headers=h))
    await ver("POST", "/api/personal/{personal_id}/desactivar", med2.pid)
    ok(client.post(f"/api/personal/{med2.pid}/reactivar", headers=h))
    await ver("POST", "/api/personal/{personal_id}/reactivar", med2.pid)
    inv = ok(
        client.post(
            "/api/personal/invitaciones",
            json={"email": f"{uuid4().hex}@prueba.invalid", "rol": "medico"},
            headers=h,
        )
    )["invitacion_id"]
    assert await ver("POST", "/api/personal/invitaciones", inv) == {"rol": "medico"}
    ok(client.post(f"/api/personal/invitaciones/{inv}/revocar", headers=h))
    await ver("POST", "/api/personal/invitaciones/{invitacion_id}/revocar", inv)

    body = {
        "nombre": "Paciente Prueba",
        "telefono": "5512345678",
        "telefono_confirmado": True,
        "medicos": [str(med.pid)],
    }
    pac = ok(client.post("/api/pacientes", json=body, headers=h))["id"]
    await ver("POST", "/api/pacientes", pac)
    ok(client.patch(f"/api/pacientes/{pac}", json={"nombre": "Otro"}, headers=h))
    await ver("PATCH", "/api/pacientes/{paciente_id}", pac)
    ok(client.post(f"/api/pacientes/{pac}/autorizacion", json={"autorizado": True}, headers=h))
    await ver("POST", "/api/pacientes/{paciente_id}/autorizacion", pac)
    async with AsyncSession(engine) as s:
        await membership.fijar_contexto(s, cid)
        await s.execute(
            text("UPDATE paciente SET optin_estado = 'rechazado' WHERE id = :i"), {"i": pac}
        )
        await s.commit()
    ok(client.post(f"/api/pacientes/{pac}/reactivar-recordatorios", headers=h))
    await ver("POST", "/api/pacientes/{paciente_id}/reactivar-recordatorios", pac)
    ok(client.put(f"/api/pacientes/{pac}/medicos", json={"medicos": [str(med2.pid)]}, headers=h))
    await ver("PUT", "/api/pacientes/{paciente_id}/medicos", pac)
    ok(client.delete(f"/api/pacientes/{pac}", headers=h))
    await ver("DELETE", "/api/pacientes/{paciente_id}", pac)
    ok(client.post(f"/api/pacientes/{pac}/restaurar", headers=h))
    await ver("POST", "/api/pacientes/{paciente_id}/restaurar", pac)

    evento = {
        "tipo": "bloqueo",
        "medico_id": str(med.pid),
        "inicio": "2030-01-07T10:00:00",
        "fin": "2030-01-07T11:00:00",
    }
    ev = ok(client.post("/api/agenda", json=evento, headers=h))["id"]
    await ver("POST", "/api/agenda", ev)
    ok(client.patch(f"/api/agenda/{ev}", json={"comentario": "Nota"}, headers=h))
    await ver("PATCH", "/api/agenda/{evento_id}", ev)
    ok(client.post(f"/api/agenda/{ev}/cancelar", headers=h))
    await ver("POST", "/api/agenda/{evento_id}/cancelar", ev)
    cob.completa()


async def test_403_queda_auditado(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid, (asis, med) = await crear_equipo(engine, platform, provider, "asistente", "medico")
    # Rol sin la acción (lo detecta `requerir`).
    h = await como(client, engine, platform, cid, asis)
    assert client.patch("/api/clinica", json={"nombre": "X"}, headers=h).status_code == 403
    # Regla dentro del endpoint (asistente no invita asistentes).
    r = client.post(
        "/api/personal/invitaciones",
        json={"email": f"{uuid4().hex}@prueba.invalid", "rol": "asistente"},
        headers=h,
    )
    assert r.status_code == 403
    h = await como(client, engine, platform, cid, med)
    assert client.get("/api/personal/invitaciones").status_code == 403

    filas = await _registros("acceso_denegado", actor=asis.uid)
    assert {(f.metadata["accion"], f.metadata["ruta"]) for f in filas} == {
        ("configurar_clinica", "/api/clinica"),
        ("agregar_asistentes", "/api/personal/invitaciones"),
    }
    assert all(f.clinica_id == cid for f in filas)
    (fila,) = await _registros("acceso_denegado", actor=med.uid)
    assert fila.metadata == {
        "accion": "ver_invitaciones",
        "metodo": "GET",
        "ruta": "/api/personal/invitaciones",
    }


async def test_sin_datos_personales_en_logs_ni_auditoria(
    client: TestClient,
    otro_client: TestClient,
    engine: AsyncEngine,
    platform: PlatformCrypto,
    provider: KeyProvider,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Recorre login, activación, pacientes y agenda capturando todos los logs (DEBUG)."""
    caplog.set_level(logging.DEBUG)
    secretos: list[str] = [PASSWORD, "otra-clave-larga-x"]

    # Activación de un admin (contraseña, secreto TOTP, nombre) y login fallido.
    inv = await crear_invitacion_completa(engine, platform, provider)
    secretos.append(inv.email)
    r = client.post("/api/auth/activar/iniciar", json={"token": inv.token, "password": PASSWORD})
    totp = r.json()["totp_secret"]
    secretos += [inv.token, totp, "Nombre Secreto Admin"]
    r = client.post(
        "/api/auth/activar/confirmar",
        json={
            "token": inv.token,
            "codigo": pyotp.TOTP(totp).now(),
            "nombre": "Nombre Secreto Admin",
            "acepta_terminos": True,
        },
    )
    secretos += r.json()["codigos_recuperacion"]
    me = client.get("/api/auth/me").json()
    uid, cid = UUID(me["id"]), UUID(me["clinica_id"])
    otro_client.post(LOGIN, json={"email": inv.email, "password": "otra-clave-larga-x"})
    otro_client.post(LOGIN, json={"email": "nadie.secreto@prueba.invalid", "password": PASSWORD})
    secretos.append("nadie.secreto@prueba.invalid")

    # Personal, paciente y cita (nombre, teléfono, comentario).
    h = _csrf(client)
    correo_medico = f"medico.{uuid4().hex}@prueba.invalid"
    secretos.append(correo_medico)
    client.post(
        "/api/personal/invitaciones", json={"email": correo_medico, "rol": "medico"}, headers=h
    )
    med = await crear_usuario(engine, platform)
    med_pid = await crear_personal(engine, provider, cid, med.id, "medico", "Doctora Secreta")
    secretos.append("Doctora Secreta")
    r = client.post(
        "/api/pacientes",
        json={
            "nombre": "Paciente Secretísimo",
            "telefono": "55 8765 4321",
            "telefono_confirmado": True,
            "medicos": [str(med_pid)],
        },
        headers=h,
    )
    assert r.status_code == 201
    pac = r.json()["id"]
    secretos += ["Paciente Secretísimo", "5587654321", "+525587654321"]
    client.post("/api/pacientes/buscar", json={"q": "Secretísimo"}, headers=h)
    r = client.post(
        "/api/agenda",
        json={
            "tipo": "consulta",
            "medico_id": str(med_pid),
            "paciente_id": pac,
            "inicio": "2030-01-07T10:00:00",
            "fin": "2030-01-07T10:30:00",
            "comentario": "Comentario secreto de la cita",
        },
        headers=h,
    )
    assert r.status_code == 201
    secretos.append("Comentario secreto de la cita")

    # 422: la respuesta no devuelve lo enviado.
    r = client.post(
        "/api/pacientes",
        json={
            "nombre": "x" * 121,
            "telefono": "55-TELSECRETO-1",
            "telefono_confirmado": True,
            "medicos": [str(med_pid)],
        },
        headers=h,
    )
    assert r.status_code == 422
    assert "TELSECRETO" not in r.text
    assert "x" * 121 not in r.text
    assert set(r.json()["detail"][0]) == {"type", "loc", "msg"}

    texto_logs = caplog.text
    filas = await _registros(actor=uid) + await _registros(entidad_id=pac)
    texto_auditoria = " ".join(str(tuple(f)) for f in filas)
    assert filas
    for s in secretos:
        assert s not in texto_logs, "dato personal en los logs"
        assert s not in texto_auditoria, "dato personal en la auditoría"


async def test_motor_oculta_parametros_sql(engine: AsyncEngine) -> None:
    assert engine.sync_engine.hide_parameters is True
