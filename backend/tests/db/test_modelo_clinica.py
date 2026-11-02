"""Restricciones de la migración 0004. Solo corre con APP_TEST_DB=1 (CI)."""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from app.db.session import clinic_session, make_engine
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.skipif(
    os.environ.get("APP_TEST_DB") != "1", reason="Pruebas de BD: solo en CI (APP_TEST_DB=1)"
)

INICIO = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)


class Entorno(NamedTuple):
    a: UUID
    b: UUID
    app: AsyncEngine
    operador: AsyncEngine
    usuarios: list[UUID]


@pytest_asyncio.fixture
async def env() -> AsyncIterator[Entorno]:
    app, operador = make_engine("app"), make_engine("operador")
    a, b = uuid4(), uuid4()
    usuarios: list[UUID] = []
    async with operador.begin() as c:
        for cid in (a, b):
            await c.execute(
                text(
                    "INSERT INTO clinica (id, nombre, tipo_persona, nombre_legal, rfc, "
                    "representante_nombre, representante_curp, dek_wrapped) "
                    "VALUES (:id, 'test', 'fisica', 'test', :x, :x, :x, :x)"
                ),
                {"id": cid, "x": b"x"},
            )
    yield Entorno(a, b, app, operador, usuarios)
    # Limpia solo lo suyo (las clínicas quedan: nadie tiene DELETE sobre `clinica`).
    for cid in (a, b):
        async with clinic_session(app, cid) as s:
            for tabla in (
                "notificacion",
                "evento_agenda",
                "paciente_medico",
                "paciente",
                "personal",
                "sala",
            ):
                await s.execute(text(f"DELETE FROM {tabla}"))  # noqa: S608
    async with app.begin() as c:
        for uid in usuarios:
            await c.execute(text("DELETE FROM usuario WHERE id = :u"), {"u": uid})
    await app.dispose()
    await operador.dispose()


async def _ejecutar(env: Entorno, clinica: UUID, sql: str, params: dict[str, Any]) -> Any:
    async with clinic_session(env.app, clinica) as s:
        return (await s.execute(text(sql), params)).scalar_one_or_none()


async def _id(env: Entorno, clinica: UUID, sql: str, params: dict[str, Any]) -> UUID:
    valor = await _ejecutar(env, clinica, sql, params)
    assert isinstance(valor, UUID)
    return valor


async def _usuario(env: Entorno) -> UUID:
    uid = uuid4()
    async with env.app.begin() as c:
        await c.execute(
            text("INSERT INTO usuario (id, email, email_idx) VALUES (:i, :e, :x)"),
            {"i": uid, "e": os.urandom(16), "x": os.urandom(16)},
        )
    env.usuarios.append(uid)
    return uid


async def _personal(
    env: Entorno, clinica: UUID, rol: str = "medico", *, activo: bool = True
) -> UUID:
    uid = await _usuario(env)
    return await _id(
        env,
        clinica,
        "INSERT INTO personal (usuario_id, rol, nombre, activo) "
        "VALUES (:u, :r, :n, :a) RETURNING id",
        {"u": uid, "r": rol, "n": b"x", "a": activo},
    )


async def _sala(env: Entorno, clinica: UUID) -> UUID:
    return await _id(env, clinica, "INSERT INTO sala (nombre) VALUES ('s') RETURNING id", {})


async def _paciente(env: Entorno, clinica: UUID, por: UUID) -> UUID:
    return await _id(
        env,
        clinica,
        "INSERT INTO paciente (nombre, telefono, telefono_idx, telefono_confirmado_por, "
        "telefono_confirmado_en, creado_por) VALUES (:n, :n, :n, :p, now(), :p) RETURNING id",
        {"n": b"x", "p": por},
    )


async def _evento(
    env: Entorno,
    clinica: UUID,
    medico: UUID,
    *,
    tipo: str = "consulta",
    paciente: UUID | None = None,
    sala: UUID | None = None,
    inicio: datetime = INICIO,
    minutos: int = 30,
    estado: str = "pendiente_envio",
    cancelada_por: str | None = None,
) -> UUID:
    return await _id(
        env,
        clinica,
        "INSERT INTO evento_agenda (tipo, medico_id, sala_id, paciente_id, rango, estado, "
        "cancelada_por, creado_por, actualizado_por) "
        "VALUES (:t, :m, :s, :p, tstzrange(CAST(:i AS timestamptz), CAST(:f AS timestamptz)), "
        ":e, :c, :m, :m) RETURNING id",
        {
            "t": tipo,
            "m": medico,
            "s": sala,
            "p": paciente,
            "i": inicio,
            "f": inicio + timedelta(minutes=minutos),
            "e": estado,
            "c": cancelada_por,
        },
    )


# --- personal ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_un_solo_admin_activo_por_clinica(env: Entorno) -> None:
    await _personal(env, env.a, "admin")
    with pytest.raises(DBAPIError):
        await _personal(env, env.a, "admin")
    await _personal(env, env.a, "admin", activo=False)  # un admin inactivo sí se permite
    await _personal(env, env.b, "admin")  # otra clínica puede tener el suyo


# --- agenda: doble reserva ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_doble_reserva_por_medico(env: Entorno) -> None:
    medico = await _personal(env, env.a)
    paciente = await _paciente(env, env.a, medico)
    await _evento(env, env.a, medico, paciente=paciente)
    with pytest.raises(DBAPIError):
        await _evento(env, env.a, medico, paciente=paciente, inicio=INICIO + timedelta(minutes=15))


@pytest.mark.asyncio
async def test_cancelada_y_contigua_no_chocan(env: Entorno) -> None:
    medico = await _personal(env, env.a)
    paciente = await _paciente(env, env.a, medico)
    await _evento(
        env, env.a, medico, paciente=paciente, estado="cancelada", cancelada_por="personal"
    )
    await _evento(env, env.a, medico, paciente=paciente)  # mismo horario que la cancelada
    await _evento(
        env, env.a, medico, paciente=paciente, inicio=INICIO + timedelta(minutes=30)
    )  # contigua


@pytest.mark.asyncio
async def test_bloqueo_ocupa_al_medico(env: Entorno) -> None:
    medico = await _personal(env, env.a)
    paciente = await _paciente(env, env.a, medico)
    await _evento(env, env.a, medico, tipo="bloqueo", estado="confirmada")
    with pytest.raises(DBAPIError):
        await _evento(env, env.a, medico, paciente=paciente)


@pytest.mark.asyncio
async def test_no_doble_reserva_por_sala(env: Entorno) -> None:
    m1, m2 = await _personal(env, env.a), await _personal(env, env.a)
    paciente = await _paciente(env, env.a, m1)
    sala = await _sala(env, env.a)
    await _evento(env, env.a, m1, paciente=paciente, sala=sala)
    with pytest.raises(DBAPIError):
        await _evento(env, env.a, m2, paciente=paciente, sala=sala)
    await _evento(env, env.a, m2, paciente=paciente)  # sin sala sí se puede


# --- agenda: checks -------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("tipo", ["consulta", "procedimiento"])
async def test_consulta_y_procedimiento_exigen_paciente(env: Entorno, tipo: str) -> None:
    medico = await _personal(env, env.a)
    with pytest.raises(DBAPIError):
        await _evento(env, env.a, medico, tipo=tipo)


@pytest.mark.asyncio
@pytest.mark.parametrize("tipo", ["otra", "bloqueo"])
async def test_otra_y_bloqueo_no_llevan_paciente(env: Entorno, tipo: str) -> None:
    medico = await _personal(env, env.a)
    paciente = await _paciente(env, env.a, medico)
    with pytest.raises(DBAPIError):
        await _evento(env, env.a, medico, tipo=tipo, paciente=paciente, estado="confirmada")
    await _evento(env, env.a, medico, tipo=tipo, estado="confirmada")


@pytest.mark.asyncio
async def test_sin_paciente_no_entra_al_flujo_de_recordatorio(env: Entorno) -> None:
    medico = await _personal(env, env.a)
    with pytest.raises(DBAPIError):
        await _evento(env, env.a, medico, tipo="otra", estado="pendiente_envio")


@pytest.mark.asyncio
async def test_duracion_minima_de_15_minutos(env: Entorno) -> None:
    medico = await _personal(env, env.a)
    with pytest.raises(DBAPIError):
        await _evento(env, env.a, medico, tipo="bloqueo", estado="confirmada", minutos=10)


@pytest.mark.asyncio
async def test_cancelada_exige_quien_cancelo(env: Entorno) -> None:
    medico = await _personal(env, env.a)
    with pytest.raises(DBAPIError):
        await _evento(env, env.a, medico, tipo="bloqueo", estado="cancelada")
    with pytest.raises(DBAPIError):
        await _evento(
            env, env.a, medico, tipo="bloqueo", estado="confirmada", cancelada_por="paciente"
        )


# --- integridad entre clínicas --------------------------------------------------------------


@pytest.mark.asyncio
async def test_evento_no_mezcla_entidades_de_otra_clinica(env: Entorno) -> None:
    medico_a = await _personal(env, env.a)
    medico_b = await _personal(env, env.b)
    paciente_b = await _paciente(env, env.b, medico_b)
    sala_b = await _sala(env, env.b)
    with pytest.raises(DBAPIError):
        await _evento(env, env.a, medico_a, paciente=paciente_b)
    with pytest.raises(DBAPIError):
        await _evento(env, env.a, medico_a, tipo="bloqueo", estado="confirmada", sala=sala_b)
    with pytest.raises(DBAPIError):
        await _evento(env, env.a, medico_b, tipo="bloqueo", estado="confirmada")


# --- paciente: opt-in -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_optin_exige_casilla_de_la_clinica(env: Entorno) -> None:
    medico = await _personal(env, env.a)
    paciente = await _paciente(env, env.a, medico)
    with pytest.raises(DBAPIError):
        await _ejecutar(
            env,
            env.a,
            "UPDATE paciente SET optin_estado = 'pendiente' WHERE id = :p RETURNING id",
            {"p": paciente},
        )
    await _ejecutar(
        env,
        env.a,
        "UPDATE paciente SET optin_estado = 'pendiente', optin_atestado_por = :m, "
        "optin_atestado_en = now() WHERE id = :p RETURNING id",
        {"p": paciente, "m": medico},
    )


# --- auditoría ------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auditoria_solo_de_la_propia_clinica(env: Entorno) -> None:
    sql = "INSERT INTO auditoria (clinica_id, accion) VALUES (:c, :a)"
    accion = f"prueba-{uuid4().hex}"
    await _ejecutar(env, env.a, sql, {"c": None, "a": accion})  # evento de plataforma
    await _ejecutar(env, env.a, sql, {"c": env.a, "a": accion})
    with pytest.raises(DBAPIError):
        await _ejecutar(env, env.a, sql, {"c": env.b, "a": accion})
    # Sin clinica_id explícito toma el contexto.
    await _ejecutar(env, env.a, "INSERT INTO auditoria (accion) VALUES (:a)", {"a": accion + "-d"})
    por_defecto = await _ejecutar(
        env,
        env.a,
        "SELECT clinica_id FROM auditoria WHERE accion = :a",
        {"a": accion + "-d"},
    )
    assert por_defecto == env.a
    # Desde otra clínica no se ve nada de A.
    visibles = await _ejecutar(
        env, env.b, "SELECT count(*) FROM auditoria WHERE accion = :a", {"a": accion}
    )
    assert visibles == 0


# --- función de login -----------------------------------------------------------------------


async def _clinicas_de(env: Entorno, usuario: UUID) -> set[UUID]:
    async with env.app.connect() as c:  # sin contexto de clínica, como en el login
        filas = await c.execute(
            text("SELECT clinica_id FROM clinicas_de_usuario(:u)"), {"u": usuario}
        )
        return set(filas.scalars().all())


@pytest.mark.asyncio
async def test_clinicas_de_usuario(env: Entorno) -> None:
    uid = await _usuario(env)
    for cid in (env.a, env.b):
        await _ejecutar(
            env,
            cid,
            "INSERT INTO personal (usuario_id, rol, nombre) VALUES (:u, 'medico', :n) RETURNING id",
            {"u": uid, "n": b"x"},
        )
    otro = await _personal(env, env.a)  # otro usuario en A: no debe aparecer
    assert otro
    assert await _clinicas_de(env, uid) == {env.a, env.b}

    async with env.operador.begin() as c:  # suspender B la excluye
        await c.execute(
            text("UPDATE clinica SET estado = 'suspendida' WHERE id = :b"), {"b": env.b}
        )
    assert await _clinicas_de(env, uid) == {env.a}


@pytest.mark.asyncio
async def test_clinicas_de_usuario_ignora_personal_inactivo(env: Entorno) -> None:
    uid = await _usuario(env)
    await _ejecutar(
        env,
        env.a,
        "INSERT INTO personal (usuario_id, rol, nombre, activo) VALUES (:u, 'medico', :n, false) "
        "RETURNING id",
        {"u": uid, "n": b"x"},
    )
    assert await _clinicas_de(env, uid) == set()


# --- permisos -------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_app_no_borra_clinica_ni_edita_plan(env: Entorno) -> None:
    with pytest.raises(DBAPIError):
        await _ejecutar(
            env, env.a, "UPDATE clinica SET plan = 'p50' WHERE id = :c RETURNING id", {"c": env.a}
        )
    with pytest.raises(DBAPIError):
        await _ejecutar(env, env.a, "DELETE FROM clinica WHERE id = :c RETURNING id", {"c": env.a})
    nombre = await _ejecutar(
        env,
        env.a,
        "UPDATE clinica SET nombre = 'nuevo' WHERE id = :c RETURNING nombre",
        {"c": env.a},
    )
    assert nombre == "nuevo"
