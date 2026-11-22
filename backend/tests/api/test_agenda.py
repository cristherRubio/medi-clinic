"""Agenda: alta, doble reserva (también concurrente), visibilidad, horario, edición con
historial, cancelación, IDOR y reglas de desactivar médico / borrar paciente."""

import asyncio
import os
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from app.auth import membership
from app.auth.platform import PlatformCrypto
from app.crypto.keys import KeyProvider
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
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

URL = "/api/agenda"


def _lunes(semanas: int = 1) -> date:
    """Un lunes futuro (las clínicas de prueba usan CDMX, UTC-6 todo el año)."""
    hoy = date.today()
    return hoy + timedelta(days=(7 - hoy.weekday()) % 7 + 7 * semanas)


def _t(d: date, hhmm: str) -> str:
    return f"{d.isoformat()}T{hhmm}:00"  # sin zona: hora de la clínica


def _utc(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)


def _paciente(c: TestClient, h: dict[str, str], medicos: list[UUID], nombre: str) -> str:
    r = c.post(
        "/api/pacientes",
        json={
            "nombre": nombre,
            "telefono": "5512345678",
            "telefono_confirmado": True,
            "medicos": [str(m) for m in medicos],
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    pid: str = r.json()["id"]
    return pid


def _evento(
    c: TestClient,
    h: dict[str, str],
    medico: UUID,
    ini: str,
    fin: str,
    *,
    tipo: str = "consulta",
    paciente: str | None = None,
    **extra: Any,
) -> Any:
    body: dict[str, Any] = {
        "tipo": tipo,
        "medico_id": str(medico),
        "inicio": ini,
        "fin": fin,
        "paciente_id": paciente,
        **extra,
    }
    return c.post(URL, json=body, headers=h)


def _crear(c: TestClient, h: dict[str, str], medico: UUID, ini: str, fin: str, **kw: Any) -> Any:
    r = _evento(c, h, medico, ini, fin, **kw)
    assert r.status_code == 201, r.text
    return r.json()


async def _sql(engine: AsyncEngine, cid: UUID, sql: str, params: dict[str, Any]) -> Any:
    async with AsyncSession(engine) as s:
        await membership.fijar_contexto(s, cid)
        r = (await s.execute(text(sql), params)).all()
        await s.commit()
    return r


def _dia(c: TestClient, d: date, **filtros: Any) -> list[dict[str, Any]]:
    r = c.get(
        URL, params={"desde": _t(d, "00:00"), "hasta": _t(d + timedelta(1), "00:00"), **filtros}
    )
    assert r.status_code == 200, r.text
    data: list[dict[str, Any]] = r.json()
    return data


async def test_crear_y_listar(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid, (admin, med) = await crear_equipo(engine, platform, provider, "admin", "medico")
    h = await como(client, engine, platform, cid, admin)
    pac = _paciente(client, h, [med.pid], "Paciente Agenda")
    d = _lunes()
    e = _crear(
        client,
        h,
        med.pid,
        _t(d, "10:00"),
        _t(d, "10:30"),
        paciente=pac,
        comentario="Traer estudios",
    )
    assert _utc(e["inicio"]) == datetime(d.year, d.month, d.day, 16, 0, tzinfo=UTC)
    assert e["estado"] == "pendiente_envio"
    assert e["paciente_nombre"] == "Paciente Agenda"
    assert e["comentario"] == "Traer estudios"
    assert e["creado_por"] == str(admin.pid)
    b = _crear(client, h, med.pid, _t(d, "12:00"), _t(d, "13:00"), tipo="bloqueo")
    assert b["estado"] == "confirmada"
    assert b["paciente_id"] is None
    assert [x["id"] for x in _dia(client, d)] == [e["id"], b["id"]]
    assert [x["id"] for x in _dia(client, d, paciente_id=pac)] == [e["id"]]
    assert _dia(client, d + timedelta(1)) == []
    assert client.get(f"{URL}/{e['id']}").json()["comentario"] == "Traer estudios"
    # La BD guarda el comentario cifrado.
    (fila,) = await _sql(
        engine, cid, "SELECT comentario FROM evento_agenda WHERE id = :i", {"i": e["id"]}
    )
    assert b"Traer estudios" not in bytes(fila.comentario)
    # Rango de consulta inválido.
    r = client.get(URL, params={"desde": _t(d, "10:00"), "hasta": _t(d, "09:00")})
    assert r.status_code == 422
    r = client.get(URL, params={"desde": _t(d, "00:00"), "hasta": _t(d + timedelta(63), "00:00")})
    assert r.status_code == 422


async def test_validaciones(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid, (admin, asis, med, inactivo) = await crear_equipo(
        engine, platform, provider, "admin", "asistente", "medico", "medico"
    )
    h = await como(client, engine, platform, cid, admin)
    pac = _paciente(client, h, [med.pid], "P")
    borrado = _paciente(client, h, [med.pid], "Borrado")
    assert client.delete(f"/api/pacientes/{borrado}", headers=h).status_code == 204
    assert client.post(f"/api/personal/{inactivo.pid}/desactivar", headers=h).status_code == 204
    sala = client.post("/api/salas", json={"nombre": "S1"}, headers=h).json()["id"]
    client.patch(f"/api/salas/{sala}", json={"activa": False}, headers=h)
    d = _lunes()
    ini, fin = _t(d, "10:00"), _t(d, "10:30")
    casos: list[tuple[UUID, str, str, dict[str, Any]]] = [
        (med.pid, ini, fin, {}),  # consulta sin paciente
        (med.pid, ini, fin, {"tipo": "bloqueo", "paciente": pac}),
        (med.pid, ini, _t(d, "10:10"), {"paciente": pac}),  # < 15 min
        (med.pid, ini, _t(d, "23:00"), {"paciente": pac}),  # > 12 h
        (med.pid, ini, _t(d + timedelta(40), "10:00"), {"tipo": "bloqueo"}),  # > 31 días
        (inactivo.pid, ini, fin, {"paciente": pac}),
        (asis.pid, ini, fin, {"paciente": pac}),
        (med.pid, ini, fin, {"paciente": borrado}),
        (med.pid, ini, fin, {"paciente": pac, "sala_id": sala}),  # sala inactiva
        (med.pid, ini, fin, {"paciente": pac, "comentario": "x" * 501}),
    ]
    for medico, i, f, kw in casos:
        assert _evento(client, h, medico, i, f, **kw).status_code == 422, kw


async def test_doble_reserva(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid, (admin, med1, med2) = await crear_equipo(
        engine, platform, provider, "admin", "medico", "medico"
    )
    h = await como(client, engine, platform, cid, admin)
    pac = _paciente(client, h, [med1.pid, med2.pid], "P")
    sala = client.post("/api/salas", json={"nombre": "S1"}, headers=h).json()["id"]
    d = _lunes()
    e = _crear(client, h, med1.pid, _t(d, "10:00"), _t(d, "10:30"), paciente=pac, sala_id=sala)
    # Mismo médico, traslape.
    r = _evento(client, h, med1.pid, _t(d, "10:15"), _t(d, "10:45"), tipo="bloqueo")
    assert r.status_code == 409
    # Otro médico, misma sala.
    r = _evento(client, h, med2.pid, _t(d, "10:00"), _t(d, "10:30"), paciente=pac, sala_id=sala)
    assert r.status_code == 409
    # Contiguo sí cabe.
    _crear(client, h, med1.pid, _t(d, "10:30"), _t(d, "11:00"), paciente=pac, sala_id=sala)
    # Cancelar libera el espacio.
    assert client.post(f"{URL}/{e['id']}/cancelar", headers=h).status_code == 200
    _crear(client, h, med2.pid, _t(d, "10:00"), _t(d, "10:30"), paciente=pac, sala_id=sala)
    # Mover encima de otro evento: 409.
    otro = _crear(client, h, med1.pid, _t(d, "12:00"), _t(d, "12:30"), paciente=pac)
    r = client.patch(
        f"{URL}/{otro['id']}", json={"inicio": _t(d, "10:30"), "fin": _t(d, "11:00")}, headers=h
    )
    assert r.status_code == 409


async def test_doble_reserva_concurrente(
    engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    """Dos reservas simultáneas del mismo horario: solo una se guarda."""
    cid, (med,) = await crear_equipo(engine, platform, provider, "medico")
    d = _lunes()
    ini = datetime(d.year, d.month, d.day, 16, 0, tzinfo=UTC)

    async def reservar(desfase: int) -> None:
        async with AsyncSession(engine) as s:
            await membership.fijar_contexto(s, cid)
            await s.execute(
                text(
                    "INSERT INTO evento_agenda (tipo, medico_id, rango, estado, creado_por, "
                    "actualizado_por) VALUES ('bloqueo', :m, tstzrange(:a, :b, '[)'), "
                    "'confirmada', :m, :m)"
                ),
                {
                    "m": med.pid,
                    "a": ini + timedelta(minutes=desfase),
                    "b": ini + timedelta(minutes=desfase + 30),
                },
            )
            await asyncio.sleep(0.3)  # transacción abierta: la otra debe esperar y chocar
            await s.commit()

    resultados = await asyncio.gather(reservar(0), reservar(10), return_exceptions=True)
    errores = [r for r in resultados if isinstance(r, BaseException)]
    assert len(errores) == 1
    assert isinstance(errores[0], IntegrityError)
    (n,) = await _sql(
        engine,
        cid,
        "SELECT count(*) AS n FROM evento_agenda WHERE medico_id = :m",
        {"m": med.pid},
    )
    assert n.n == 1


async def test_visibilidad_medico(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid, (admin, med1, med2) = await crear_equipo(
        engine, platform, provider, "admin", "medico", "medico"
    )
    h = await como(client, engine, platform, cid, admin)
    ajeno = _paciente(client, h, [med2.pid], "Ajeno")
    d = _lunes()
    de_med2 = _crear(client, h, med2.pid, _t(d, "10:00"), _t(d, "10:30"), paciente=ajeno)

    h = await como(client, engine, platform, cid, med1)
    propio = _paciente(client, h, [], "Propio")
    mio = _crear(client, h, med1.pid, _t(d, "10:00"), _t(d, "10:30"), paciente=propio)
    _crear(client, h, med1.pid, _t(d, "13:00"), _t(d, "14:00"), tipo="bloqueo")
    # Agenda ajena o paciente no vinculado: no.
    assert (
        _evento(client, h, med2.pid, _t(d, "11:00"), _t(d, "11:30"), paciente=propio).status_code
        == 403
    )
    assert (
        _evento(client, h, med2.pid, _t(d, "11:00"), _t(d, "11:30"), tipo="bloqueo").status_code
        == 403
    )
    assert (
        _evento(client, h, med1.pid, _t(d, "11:00"), _t(d, "11:30"), paciente=ajeno).status_code
        == 422
    )
    # Solo ve su agenda, aunque filtre por otro médico.
    assert {x["medico_id"] for x in _dia(client, d)} == {str(med1.pid)}
    assert _dia(client, d, medico_id=str(med2.pid)) == []
    u = f"{URL}/{de_med2['id']}"
    assert client.get(u).status_code == 404
    assert client.get(f"{u}/historial").status_code == 404
    assert client.patch(u, json={"comentario": "x"}, headers=h).status_code == 404
    assert client.post(f"{u}/cancelar", headers=h).status_code == 404
    # Su propia cita no puede pasarla a otro médico.
    r = client.patch(f"{URL}/{mio['id']}", json={"medico_id": str(med2.pid)}, headers=h)
    assert r.status_code == 403


async def test_vinculo_automatico(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid, (asis, med1, med2) = await crear_equipo(
        engine, platform, provider, "asistente", "medico", "medico"
    )
    h = await como(client, engine, platform, cid, asis)
    pac = _paciente(client, h, [med1.pid], "P")
    d = _lunes()
    e = _crear(client, h, med2.pid, _t(d, "10:00"), _t(d, "10:30"), paciente=pac)
    medicos = client.get(f"/api/pacientes/{pac}").json()["medicos"]
    assert sorted(medicos) == sorted([str(med1.pid), str(med2.pid)])
    (fila,) = await _sql(
        engine, cid, "SELECT metadata FROM auditoria WHERE entidad_id = :i", {"i": e["id"]}
    )
    assert fila.metadata["vinculo_automatico"] is True
    await como(client, engine, platform, cid, med2)
    assert client.get(f"/api/pacientes/{pac}").status_code == 200


async def test_horario_laboral_y_zona(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid, (admin, med) = await crear_equipo(engine, platform, provider, "admin", "medico")
    h = await como(client, engine, platform, cid, admin)
    pac = _paciente(client, h, [med.pid], "P")
    d = _lunes()
    r = client.patch(
        "/api/clinica", json={"horario_laboral": {"lun": [["09:00", "14:00"]]}}, headers=h
    )
    assert r.status_code == 200
    assert (
        _evento(client, h, med.pid, _t(d, "15:00"), _t(d, "15:30"), paciente=pac).status_code == 422
    )
    forzada = _crear(
        client, h, med.pid, _t(d, "15:00"), _t(d, "15:30"), paciente=pac, fuera_de_horario=True
    )
    _crear(client, h, med.pid, _t(d, "18:00"), _t(d, "19:00"), tipo="bloqueo")  # bloqueo: libre
    dentro = _crear(client, h, med.pid, _t(d, "09:00"), _t(d, "09:30"), paciente=pac)
    u = f"{URL}/{dentro['id']}"
    body = {"inicio": _t(d, "16:00"), "fin": _t(d, "16:30")}
    assert client.patch(u, json=body, headers=h).status_code == 422
    assert client.patch(u, json={**body, "fuera_de_horario": True}, headers=h).status_code == 200
    historial = client.get(f"{URL}/{forzada['id']}/historial").json()
    assert historial[0]["fuera_de_horario"] is True
    # Fechas sin zona: hora de la clínica (Tijuana); con zona explícita: se respeta.
    client.patch(
        "/api/clinica", json={"zona_horaria": "America/Tijuana", "horario_laboral": {}}, headers=h
    )
    d2 = _lunes(3)
    e = _crear(client, h, med.pid, _t(d2, "10:00"), _t(d2, "10:30"), tipo="bloqueo")
    esperado = datetime(d2.year, d2.month, d2.day, 10, 0, tzinfo=ZoneInfo("America/Tijuana"))
    assert _utc(e["inicio"]) == esperado.astimezone(UTC)
    e = _crear(
        client,
        h,
        med.pid,
        f"{d2.isoformat()}T13:00:00-06:00",
        f"{d2.isoformat()}T13:30:00-06:00",
        tipo="bloqueo",
    )
    assert _utc(e["inicio"]) == datetime(d2.year, d2.month, d2.day, 19, 0, tzinfo=UTC)


async def test_editar_y_historial(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid, (admin, asis, med) = await crear_equipo(
        engine, platform, provider, "admin", "asistente", "medico"
    )
    h = await como(client, engine, platform, cid, admin)
    p1 = _paciente(client, h, [med.pid], "Primero")
    p2 = _paciente(client, h, [med.pid], "Segundo")
    d = _lunes()
    e = _crear(client, h, med.pid, _t(d, "10:00"), _t(d, "10:30"), paciente=p1)
    u = f"{URL}/{e['id']}"
    # Simula que el paciente confirmó (lo hará el webhook en la Fase 2).
    await _sql(
        engine,
        cid,
        "UPDATE evento_agenda SET estado = 'confirmada', confirmado_en = now() "
        "WHERE id = :i RETURNING id",
        {"i": e["id"]},
    )
    h = await como(client, engine, platform, cid, asis)
    # Solo comentario: no se reprograma.
    r = client.patch(u, json={"comentario": "Nota"}, headers=h)
    assert r.json()["estado"] == "confirmada"
    # Cambio de paciente: vuelve a pendiente_envio y queda trazado.
    r = client.patch(u, json={"paciente_id": p2}, headers=h)
    assert r.status_code == 200
    assert r.json()["paciente_nombre"] == "Segundo"
    assert r.json()["estado"] == "pendiente_envio"
    assert r.json()["actualizado_por"] == str(asis.pid)
    assert client.patch(u, json={"comentario": ""}, headers=h).json()["comentario"] is None
    historial = client.get(f"{u}/historial").json()
    assert [x["accion"] for x in historial] == [
        "evento_creado",
        "evento_editado",
        "evento_editado",
        "evento_editado",
    ]
    assert historial[0]["quien"] == "Persona 0"
    cambio = historial[2]
    assert cambio["quien"] == "Persona 1"
    assert cambio["personal_id"] == str(asis.pid)
    assert cambio["campos"] == ["paciente_id"]
    assert cambio["paciente_anterior"] == {"id": p1, "nombre": "Primero"}
    assert cambio["paciente_nuevo"] == {"id": p2, "nombre": "Segundo"}
    assert cambio["reprogramado"] is True
    assert historial[1]["reprogramado"] is False
    # Cambios inválidos.
    assert client.patch(u, json={}, headers=h).status_code == 422
    assert client.patch(u, json={"medico_id": None}, headers=h).status_code == 422
    assert client.patch(u, json={"paciente_id": None}, headers=h).status_code == 422
    b = _crear(client, h, med.pid, _t(d, "12:00"), _t(d, "13:00"), tipo="bloqueo")
    r = client.patch(f"{URL}/{b['id']}", json={"paciente_id": p1}, headers=h)
    assert r.status_code == 422


async def test_cancelar(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid, (admin, med) = await crear_equipo(engine, platform, provider, "admin", "medico")
    h = await como(client, engine, platform, cid, admin)
    pac = _paciente(client, h, [med.pid], "P")
    d = _lunes()
    e = _crear(client, h, med.pid, _t(d, "10:00"), _t(d, "10:30"), paciente=pac)
    u = f"{URL}/{e['id']}"
    r = client.post(f"{u}/cancelar", headers=h)
    assert r.status_code == 200
    assert r.json()["estado"] == "cancelada"
    assert r.json()["cancelada_por"] == "personal"
    assert client.post(f"{u}/cancelar", headers=h).status_code == 409
    assert client.patch(u, json={"comentario": "x"}, headers=h).status_code == 409
    assert _dia(client, d) == []
    assert [x["id"] for x in _dia(client, d, incluir_canceladas=True)] == [e["id"]]
    assert client.delete(u, headers=h).status_code == 405  # las citas no se borran


async def test_idor_otra_clinica(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid_a, (admin_a, med_a) = await crear_equipo(engine, platform, provider, "admin", "medico")
    cid_b, (admin_b, med_b) = await crear_equipo(engine, platform, provider, "admin", "medico")
    h = await como(client, engine, platform, cid_a, admin_a)
    pac_a = _paciente(client, h, [med_a.pid], "A")
    d = _lunes()
    e = _crear(client, h, med_a.pid, _t(d, "10:00"), _t(d, "10:30"), paciente=pac_a)
    h = await como(client, engine, platform, cid_b, admin_b)
    u = f"{URL}/{e['id']}"
    assert client.get(u).status_code == 404
    assert client.get(f"{u}/historial").status_code == 404
    assert client.patch(u, json={"comentario": "x"}, headers=h).status_code == 404
    assert client.post(f"{u}/cancelar", headers=h).status_code == 404
    assert _dia(client, d) == []
    # No puede usar médicos ni pacientes de otra clínica.
    pac_b = _paciente(client, h, [med_b.pid], "B")
    assert (
        _evento(client, h, med_a.pid, _t(d, "12:00"), _t(d, "12:30"), paciente=pac_b).status_code
        == 422
    )
    assert (
        _evento(client, h, med_b.pid, _t(d, "12:00"), _t(d, "12:30"), paciente=pac_a).status_code
        == 422
    )


async def test_desactivar_medico_con_citas_futuras(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid, (admin, med, med_pasado) = await crear_equipo(
        engine, platform, provider, "admin", "medico", "medico"
    )
    h = await como(client, engine, platform, cid, admin)
    pac = _paciente(client, h, [med.pid, med_pasado.pid], "P")
    d = _lunes()
    e = _crear(client, h, med.pid, _t(d, "10:00"), _t(d, "10:30"), paciente=pac)
    _crear(client, h, med.pid, _t(d, "12:00"), _t(d, "13:00"), tipo="bloqueo")  # no cuenta
    assert client.post(f"/api/personal/{med.pid}/desactivar", headers=h).status_code == 409
    client.post(f"{URL}/{e['id']}/cancelar", headers=h)
    assert client.post(f"/api/personal/{med.pid}/desactivar", headers=h).status_code == 204
    # Citas pasadas (se permiten) no bloquean.
    ayer = date.today() - timedelta(days=7)
    _crear(client, h, med_pasado.pid, _t(ayer, "10:00"), _t(ayer, "10:30"), paciente=pac)
    assert client.post(f"/api/personal/{med_pasado.pid}/desactivar", headers=h).status_code == 204


async def test_borrar_paciente_con_citas_futuras(
    client: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid, (admin, med) = await crear_equipo(engine, platform, provider, "admin", "medico")
    h = await como(client, engine, platform, cid, admin)
    pac = _paciente(client, h, [med.pid], "P")
    d = _lunes()
    e = _crear(client, h, med.pid, _t(d, "10:00"), _t(d, "10:30"), paciente=pac)
    assert client.delete(f"/api/pacientes/{pac}", headers=h).status_code == 409
    client.post(f"{URL}/{e['id']}/cancelar", headers=h)
    assert client.delete(f"/api/pacientes/{pac}", headers=h).status_code == 204
