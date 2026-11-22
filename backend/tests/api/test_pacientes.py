"""Pacientes: alta, visibilidad por rol, IDOR, teléfono, autorización, vínculos y borrado."""

import os
from typing import Any
from uuid import UUID, uuid4

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

URL = "/api/pacientes"
TEL = "55 1234 5678"
TEL_E164 = "+525512345678"


def _alta(
    c: TestClient,
    h: dict[str, str],
    medicos: list[UUID],
    *,
    nombre: str = "Paciente Prueba",
    telefono: str = TEL,
    **extra: Any,
) -> Any:
    body = {
        "nombre": nombre,
        "telefono": telefono,
        "telefono_confirmado": True,
        "medicos": [str(m) for m in medicos],
        **extra,
    }
    return c.post(URL, json=body, headers=h)


def _crear(c: TestClient, h: dict[str, str], medicos: list[UUID], **kw: Any) -> dict[str, Any]:
    r = _alta(c, h, medicos, **kw)
    assert r.status_code == 201, r.text
    data: dict[str, Any] = r.json()
    return data


async def _sql(engine: AsyncEngine, cid: UUID, sql: str, params: dict[str, Any]) -> Any:
    async with AsyncSession(engine) as s:
        await membership.fijar_contexto(s, cid)
        r = (await s.execute(text(sql), params)).all()
        await s.commit()
    return r


async def test_crear_y_ver(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid, (admin, med) = await crear_equipo(engine, platform, provider, "admin", "medico")
    h = await como(client, engine, platform, cid, admin)
    p = _crear(client, h, [med.pid])
    assert p["nombre"] == "Paciente Prueba"
    assert p["telefono"] == TEL_E164
    assert p["optin_estado"] == "sin_solicitar"
    assert p["optin_atestado_en"] is None
    assert p["medicos"] == [str(med.pid)]
    assert p["telefono_repetido"] is False
    r = client.get(f"{URL}/{p['id']}")
    assert r.status_code == 200
    assert r.json()["nombre"] == "Paciente Prueba"
    auditados = await _sql(
        engine,
        cid,
        "SELECT accion FROM auditoria WHERE entidad = 'paciente' AND entidad_id = :i",
        {"i": p["id"]},
    )
    assert [a.accion for a in auditados] == ["paciente_creado"]


async def test_crear_vinculos_por_rol(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid, (admin, asis, med, med2) = await crear_equipo(
        engine, platform, provider, "admin", "asistente", "medico", "medico"
    )
    # Admin y asistente deben vincular al menos un médico.
    for m in (admin, asis):
        h = await como(client, engine, platform, cid, m)
        assert _alta(client, h, []).status_code == 422
    # El médico queda vinculado a sí mismo; no puede vincular a otros.
    h = await como(client, engine, platform, cid, med)
    assert _crear(client, h, [])["medicos"] == [str(med.pid)]
    assert _crear(client, h, [med.pid])["medicos"] == [str(med.pid)]
    assert _alta(client, h, [med2.pid]).status_code == 403


async def test_medico_invalido(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid, (admin, asis, med, inactivo) = await crear_equipo(
        engine, platform, provider, "admin", "asistente", "medico", "medico"
    )
    _, (ajeno,) = await crear_equipo(engine, platform, provider, "medico")
    h = await como(client, engine, platform, cid, admin)
    assert client.post(f"/api/personal/{inactivo.pid}/desactivar", headers=h).status_code == 204
    for invalido in (inactivo.pid, asis.pid, ajeno.pid, uuid4()):
        assert _alta(client, h, [med.pid, invalido]).status_code == 422


async def test_entradas_invalidas(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid, (admin, med) = await crear_equipo(engine, platform, provider, "admin", "medico")
    h = await como(client, engine, platform, cid, admin)
    assert _alta(client, h, [med.pid], telefono_confirmado=False).status_code == 422
    body = {"nombre": "X", "telefono": TEL, "medicos": [str(med.pid)]}
    assert client.post(URL, json=body, headers=h).status_code == 422  # sin confirmar
    assert _alta(client, h, [med.pid], nombre="   ").status_code == 422
    assert _alta(client, h, [med.pid], telefono="123").status_code == 422
    assert _alta(client, h, [med.pid], telefono="   ").status_code == 422


async def test_visibilidad_por_rol(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid, (admin, asis, med1, med2) = await crear_equipo(
        engine, platform, provider, "admin", "asistente", "medico", "medico"
    )
    h = await como(client, engine, platform, cid, admin)
    p1 = _crear(client, h, [med1.pid], nombre="Uno")
    p2 = _crear(client, h, [med2.pid], nombre="Dos")
    for m in (admin, asis):
        await como(client, engine, platform, cid, m)
        assert {p["id"] for p in client.get(URL).json()} == {p1["id"], p2["id"]}
    h = await como(client, engine, platform, cid, med1)
    assert [p["id"] for p in client.get(URL).json()] == [p1["id"]]
    assert client.get(f"{URL}/{p1['id']}").status_code == 200
    # Paciente de otro médico: 404 uniforme en lectura y en mutaciones.
    assert client.get(f"{URL}/{p2['id']}").status_code == 404
    assert client.patch(f"{URL}/{p2['id']}", json={"nombre": "Z"}, headers=h).status_code == 404
    r = client.post(f"{URL}/{p2['id']}/autorizacion", json={"autorizado": True}, headers=h)
    assert r.status_code == 404
    r = client.post(f"{URL}/buscar", json={"q": "o"}, headers=h)
    assert [p["id"] for p in r.json()] == [p1["id"]]
    # El médico edita a los suyos.
    r = client.patch(f"{URL}/{p1['id']}", json={"nombre": "Uno Bis"}, headers=h)
    assert r.status_code == 200
    assert r.json()["nombre"] == "Uno Bis"


async def test_idor_otra_clinica(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid_a, (admin_a, med_a) = await crear_equipo(engine, platform, provider, "admin", "medico")
    cid_b, (admin_b, med_b) = await crear_equipo(engine, platform, provider, "admin", "medico")
    h = await como(client, engine, platform, cid_a, admin_a)
    pid = _crear(client, h, [med_a.pid])["id"]
    h = await como(client, engine, platform, cid_b, admin_b)
    u = f"{URL}/{pid}"
    assert client.get(u).status_code == 404
    assert client.patch(u, json={"nombre": "Z"}, headers=h).status_code == 404
    assert client.post(f"{u}/autorizacion", json={"autorizado": True}, headers=h).status_code == 404
    assert client.post(f"{u}/reactivar-recordatorios", headers=h).status_code == 404
    r = client.put(f"{u}/medicos", json={"medicos": [str(med_b.pid)]}, headers=h)
    assert r.status_code == 404
    assert client.delete(u, headers=h).status_code == 404
    assert client.post(f"{u}/restaurar", headers=h).status_code == 404
    assert client.get(URL).json() == []
    assert client.get(f"{URL}?eliminados=true").json() == []


async def test_cambio_de_telefono(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid, (asis, med) = await crear_equipo(engine, platform, provider, "asistente", "medico")
    h = await como(client, engine, platform, cid, asis)
    p = _crear(client, h, [med.pid])
    u = f"{URL}/{p['id']}"
    r = client.post(f"{u}/autorizacion", json={"autorizado": True}, headers=h)
    assert r.json()["optin_atestado_en"] is not None
    # Sin confirmar: 422.
    assert client.patch(u, json={"telefono": "5598765432"}, headers=h).status_code == 422
    r = client.patch(u, json={"telefono": "5598765432", "telefono_confirmado": False}, headers=h)
    assert r.status_code == 422
    # Mismo número en otro formato, o solo el nombre: el opt-in se conserva.
    r = client.patch(
        u, json={"telefono": "+52 1 55 1234 5678", "telefono_confirmado": True}, headers=h
    )
    assert r.status_code == 200
    assert r.json()["optin_atestado_en"] is not None
    r = client.patch(u, json={"nombre": "Otro Nombre"}, headers=h)
    assert r.json()["optin_atestado_en"] is not None
    # Número nuevo confirmado: se guarda y se reinicia el opt-in.
    r = client.patch(u, json={"telefono": "5598765432", "telefono_confirmado": True}, headers=h)
    assert r.status_code == 200
    assert r.json()["telefono"] == "+525598765432"
    assert r.json()["optin_estado"] == "sin_solicitar"
    assert r.json()["optin_atestado_en"] is None
    # Cambios inválidos.
    assert client.patch(u, json={}, headers=h).status_code == 422
    assert client.patch(u, json={"nombre": None}, headers=h).status_code == 422
    assert client.patch(u, json={"nombre": "  "}, headers=h).status_code == 422
    r = client.patch(u, json={"no_enviar_recordatorios": True}, headers=h)
    assert r.json()["no_enviar_recordatorios"] is True


async def test_telefono_repetido_avisa(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid, (admin, med) = await crear_equipo(engine, platform, provider, "admin", "medico")
    h = await como(client, engine, platform, cid, admin)
    assert _crear(client, h, [med.pid])["telefono_repetido"] is False
    assert _crear(client, h, [med.pid], telefono="+5215512345678")["telefono_repetido"] is True
    otro = _crear(client, h, [med.pid], telefono="5500000000")
    assert otro["telefono_repetido"] is False
    r = client.patch(
        f"{URL}/{otro['id']}", json={"telefono": TEL, "telefono_confirmado": True}, headers=h
    )
    assert r.json()["telefono_repetido"] is True
    # Otra clínica con el mismo teléfono no cuenta.
    cid2, (admin2, med2) = await crear_equipo(engine, platform, provider, "admin", "medico")
    h = await como(client, engine, platform, cid2, admin2)
    assert _crear(client, h, [med2.pid])["telefono_repetido"] is False


async def test_autorizacion_y_reactivacion(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid, (med,) = await crear_equipo(engine, platform, provider, "medico")
    h = await como(client, engine, platform, cid, med)
    pid = _crear(client, h, [])["id"]
    u = f"{URL}/{pid}"
    r = client.post(f"{u}/autorizacion", json={"autorizado": True}, headers=h)
    assert r.status_code == 200
    atestado = r.json()["optin_atestado_en"]
    assert atestado is not None
    # Marcar de nuevo no cambia nada.
    r = client.post(f"{u}/autorizacion", json={"autorizado": True}, headers=h)
    assert r.json()["optin_atestado_en"] == atestado
    # Desmarcar vuelve a sin_solicitar.
    r = client.post(f"{u}/autorizacion", json={"autorizado": False}, headers=h)
    assert r.json()["optin_estado"] == "sin_solicitar"
    assert r.json()["optin_atestado_en"] is None
    # Sin rechazo no hay nada que reactivar.
    assert client.post(f"{u}/reactivar-recordatorios", headers=h).status_code == 409
    # Simula el rechazo del paciente (lo hará el webhook en la Fase 2).
    await _sql(
        engine,
        cid,
        "UPDATE paciente SET optin_atestado_por = :m, optin_atestado_en = now(), "
        "optin_estado = 'rechazado', optin_respondido_en = now() WHERE id = :i RETURNING id",
        {"m": med.pid, "i": pid},
    )
    r = client.post(f"{u}/reactivar-recordatorios", headers=h)
    assert r.status_code == 200
    assert r.json()["optin_estado"] == "sin_solicitar"
    assert r.json()["optin_atestado_en"] is None
    acciones = await _sql(
        engine,
        cid,
        "SELECT accion FROM auditoria WHERE entidad_id = :i ORDER BY creado_en",
        {"i": pid},
    )
    assert [a.accion for a in acciones] == [
        "paciente_creado",
        "paciente_autorizacion",
        "paciente_autorizacion",
        "recordatorios_reactivados",
    ]


async def test_vincular(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid, (asis, med1, med2) = await crear_equipo(
        engine, platform, provider, "asistente", "medico", "medico"
    )
    h = await como(client, engine, platform, cid, asis)
    pid = _crear(client, h, [med1.pid])["id"]
    u = f"{URL}/{pid}/medicos"
    r = client.put(u, json={"medicos": [str(med2.pid)]}, headers=h)
    assert r.status_code == 200
    assert r.json()["medicos"] == [str(med2.pid)]
    r = client.put(u, json={"medicos": [str(med1.pid), str(med2.pid)]}, headers=h)
    assert sorted(r.json()["medicos"]) == sorted([str(med1.pid), str(med2.pid)])
    assert client.put(u, json={"medicos": []}, headers=h).status_code == 422
    assert client.put(u, json={"medicos": [str(asis.pid)]}, headers=h).status_code == 422
    # El médico ve al paciente pero no puede vincular.
    h = await como(client, engine, platform, cid, med1)
    assert client.put(u, json={"medicos": [str(med1.pid)]}, headers=h).status_code == 403


async def test_borrado_logico_solo_admin(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid, (admin, asis, med) = await crear_equipo(
        engine, platform, provider, "admin", "asistente", "medico"
    )
    h = await como(client, engine, platform, cid, asis)
    pid = _crear(client, h, [med.pid])["id"]
    u = f"{URL}/{pid}"
    assert client.delete(u, headers=h).status_code == 403
    h = await como(client, engine, platform, cid, admin)
    assert client.delete(u, headers=h).status_code == 204
    assert client.delete(u, headers=h).status_code == 404
    assert client.get(URL).json() == []
    assert [p["id"] for p in client.get(f"{URL}?eliminados=true").json()] == [pid]
    assert client.get(u).json()["eliminado_en"] is not None  # el admin lo ve
    # Asistente y médico ya no lo ven ni pueden restaurarlo.
    for m in (asis, med):
        h2 = await como(client, engine, platform, cid, m)
        assert client.get(URL).json() == []
        assert client.get(u).status_code == 404
        assert client.get(f"{URL}?eliminados=true").status_code == 403
        assert client.patch(u, json={"nombre": "Z"}, headers=h2).status_code == 404
        assert client.post(f"{u}/restaurar", headers=h2).status_code == 403
    h = await como(client, engine, platform, cid, admin)
    r = client.post(f"{u}/restaurar", headers=h)
    assert r.status_code == 200
    assert r.json()["eliminado_en"] is None
    assert client.post(f"{u}/restaurar", headers=h).status_code == 404
    assert [p["id"] for p in client.get(URL).json()] == [pid]


async def test_buscar_por_nombre(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid, (admin, med) = await crear_equipo(engine, platform, provider, "admin", "medico")
    h = await como(client, engine, platform, cid, admin)
    jose = _crear(client, h, [med.pid], nombre="José Pérez")["id"]
    _crear(client, h, [med.pid], nombre="Ana López")

    def ids(q: str) -> list[str]:
        r = client.post(f"{URL}/buscar", json={"q": q}, headers=h)
        assert r.status_code == 200
        return [p["id"] for p in r.json()]

    assert ids("jose") == [jose]
    assert ids("PEREZ") == [jose]
    assert ids("zzz") == []
    assert len(ids("ó")) == 2
    assert client.post(f"{URL}/buscar", json={"q": "   "}, headers=h).status_code == 422
    assert client.post(f"{URL}/buscar", json={"q": "jose"}).status_code == 403  # sin CSRF


async def test_bd_guarda_solo_cifrado(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid, (admin, med) = await crear_equipo(engine, platform, provider, "admin", "medico")
    h = await como(client, engine, platform, cid, admin)
    pid = _crear(client, h, [med.pid], nombre="Nombre Secreto")["id"]
    (fila,) = await _sql(
        engine,
        cid,
        "SELECT nombre, telefono, telefono_idx FROM paciente WHERE id = :i",
        {"i": pid},
    )
    assert b"Nombre Secreto" not in bytes(fila.nombre)
    assert b"5512345678" not in bytes(fila.telefono)
    assert bytes(fila.telefono_idx) == platform.telefono_idx(TEL_E164)
