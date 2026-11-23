"""Rotación de llaves: DEK de clínica por lotes (reanudable), KEK y registro de columnas."""

import os
import struct
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from app.auth import membership
from app.auth.platform import PlatformCrypto
from app.crypto import rotacion
from app.crypto.columnas import (
    BYTEA_NO_CIFRADAS,
    COLUMNAS_CLINICA,
    COLUMNAS_PLATAFORMA,
    params,
)
from app.crypto.envelope import unwrap_dek
from app.crypto.fields import FieldCipher, FieldContext
from app.crypto.keys import KeyProvider
from app.db.session import make_engine
from app.scripts.rotacion import _argumentos, _correr
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


class _Keks(KeyProvider):
    """Varias versiones de KEK en memoria (como tener kek_v1 y kek_v2 montadas)."""

    def __init__(self, keks: dict[int, bytes], activa: int) -> None:
        self._keks, self._activa = keks, activa

    @property
    def active_version(self) -> int:
        return self._activa

    def get_kek(self, version: int) -> bytes:
        return self._keks[version]


@pytest_asyncio.fixture
async def migrador() -> AsyncIterator[AsyncEngine]:
    e = make_engine("migrador")
    yield e
    await e.dispose()


async def _datos(
    c: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> tuple[UUID, dict[str, str], str]:
    """Clínica con un valor en cada columna cifrada. Devuelve (cid, headers, paciente_id)."""
    cid, (admin, med) = await crear_equipo(engine, platform, provider, "admin", "medico")
    h = await como(c, engine, platform, cid, admin)
    r = c.patch(f"/api/personal/{med.pid}", json={"contacto_preferido": "Contacto X"}, headers=h)
    assert r.status_code == 200
    r = c.post(
        "/api/pacientes",
        json={
            "nombre": "Paciente Rotado",
            "telefono": "5512345678",
            "telefono_confirmado": True,
            "medicos": [str(med.pid)],
        },
        headers=h,
    )
    assert r.status_code == 201
    pac = r.json()["id"]
    r = c.post(
        "/api/agenda",
        json={
            "tipo": "consulta",
            "medico_id": str(med.pid),
            "paciente_id": pac,
            "inicio": "2030-01-07T10:00:00",
            "fin": "2030-01-07T10:30:00",
            "comentario": "Comentario rotado",
        },
        headers=h,
    )
    assert r.status_code == 201
    return cid, h, pac


def _foto(c: TestClient) -> dict[str, Any]:
    """Lo que la API devuelve descifrado (para comparar antes y después)."""
    agenda = c.get(
        "/api/agenda", params={"desde": "2030-01-07T00:00:00", "hasta": "2030-01-08T00:00:00"}
    )
    return {
        "pacientes": c.get("/api/pacientes").json(),
        "personal": c.get("/api/personal").json(),
        "agenda": [(e["id"], e["comentario"], e["paciente_nombre"]) for e in agenda.json()],
    }


async def _pendientes(migrador: AsyncEngine, cid: UUID, version: int) -> int:
    async with AsyncSession(migrador) as db:
        return sum(
            [
                (await db.execute(col.contar, params(cid, struct.pack(">I", version)))).scalar_one()
                for col in COLUMNAS_CLINICA
            ]
        )


async def _dek(migrador: AsyncEngine, cid: UUID) -> Any:
    async with AsyncSession(migrador) as db:
        return (
            await db.execute(
                text(
                    "SELECT dek_version, dek_anterior_version, dek_anterior_wrapped "
                    "FROM clinica WHERE id = :c"
                ),
                {"c": cid},
            )
        ).one()


async def test_rotar_dek_recifra_todo_y_la_api_sigue_leyendo(
    client: TestClient,
    engine: AsyncEngine,
    migrador: AsyncEngine,
    platform: PlatformCrypto,
    provider: KeyProvider,
) -> None:
    cid, _, _ = await _datos(client, engine, platform, provider)
    antes = _foto(client)
    assert await _pendientes(migrador, cid, 2) == 9  # todo está en v1

    r = await rotacion.rotar_dek_clinica(migrador, provider, cid, lote=2, espera=0)
    # 3 legales + nombre de 2 personas + 1 contacto + nombre y teléfono + 1 comentario
    assert (r.dek_version, r.recifrados, r.nueva) == (2, 9, True)
    assert await _pendientes(migrador, cid, 2) == 0
    dek = await _dek(migrador, cid)
    assert (dek.dek_version, dek.dek_anterior_version) == (2, None)
    assert _foto(client) == antes

    # Una segunda rotación también funciona.
    r = await rotacion.rotar_dek_clinica(migrador, provider, cid, espera=0)
    assert (r.dek_version, r.recifrados) == (3, 9)
    assert _foto(client) == antes

    async with AsyncSession(migrador) as db:
        acciones = (
            await db.execute(
                text(
                    "SELECT accion, metadata FROM auditoria "
                    "WHERE entidad = 'clinica' AND entidad_id = :c ORDER BY creado_en"
                ),
                {"c": cid},
            )
        ).all()
    assert [(a.accion, a.metadata["dek_version"]) for a in acciones] == [
        ("dek_rotacion_iniciada", 2),
        ("dek_clinica_rotada", 2),
        ("dek_rotacion_iniciada", 3),
        ("dek_clinica_rotada", 3),
    ]


async def test_rotacion_reanudable_y_escritura_con_la_dek_vieja(
    client: TestClient,
    engine: AsyncEngine,
    migrador: AsyncEngine,
    platform: PlatformCrypto,
    provider: KeyProvider,
) -> None:
    cid, h, pac = await _datos(client, engine, platform, provider)
    assert await rotacion.iniciar_rotacion_dek(migrador, provider, cid) is True
    assert await rotacion.iniciar_rotacion_dek(migrador, provider, cid) is False  # ya en curso

    # Durante la rotación la API lee lo viejo y escribe con la DEK nueva.
    assert client.get(f"/api/pacientes/{pac}").json()["nombre"] == "Paciente Rotado"
    nuevo = client.post(
        "/api/pacientes",
        json={
            "nombre": "Nuevo",
            "telefono": "5500000000",
            "telefono_confirmado": True,
            "medicos": client.get(f"/api/pacientes/{pac}").json()["medicos"],
        },
        headers=h,
    ).json()["id"]
    async with AsyncSession(migrador) as db:
        blob = (
            await db.execute(text("SELECT nombre FROM paciente WHERE id = :i"), {"i": nuevo})
        ).scalar_one()
    assert FieldCipher({2: b"\0" * 32}, 2).key_version_of(bytes(blob)) == 2

    # Se recifra todo, pero una petición que cargó la DEK vieja escribe después.
    await rotacion._recifrar(migrador, provider, cid, 500)
    dek = await _dek(migrador, cid)
    vieja = FieldCipher(
        {1: unwrap_dek(provider, bytes(dek.dek_anterior_wrapped), f"clinica|{cid}|v1")}, 1
    )
    async with AsyncSession(engine) as db:
        await membership.fijar_contexto(db, cid)
        await db.execute(
            text("UPDATE paciente SET nombre = :n WHERE id = :i"),
            {
                "n": vieja.encrypt(
                    "Escrito Tarde", FieldContext("paciente", "nombre", cid, UUID(pac))
                ),
                "i": pac,
            },
        )
        await db.commit()
    assert await rotacion._terminar(migrador, cid, 0) is False  # no borra la DEK anterior
    assert (await _dek(migrador, cid)).dek_anterior_version == 1

    # Volver a correr reanuda y termina.
    r = await rotacion.rotar_dek_clinica(migrador, provider, cid, espera=0)
    assert (r.dek_version, r.nueva, r.recifrados) == (2, False, 1)
    assert (await _dek(migrador, cid)).dek_anterior_version is None
    assert client.get(f"/api/pacientes/{pac}").json()["nombre"] == "Escrito Tarde"


async def test_rotar_kek(
    client: TestClient,
    engine: AsyncEngine,
    migrador: AsyncEngine,
    platform: PlatformCrypto,
    provider: KeyProvider,
) -> None:
    cid, _, pac = await _datos(client, engine, platform, provider)
    await rotacion.iniciar_rotacion_dek(migrador, provider, cid)  # también hay DEK anterior
    k1, k2 = provider.get_kek(1), os.urandom(32)

    ambas = _Keks({1: k1, 2: k2}, 2)
    assert await rotacion.rotar_kek(migrador, ambas, clinicas=[cid], plataforma=False) == 2
    assert await rotacion.rotar_kek(migrador, ambas, clinicas=[cid], plataforma=False) == 0

    e = await rotacion.estado(migrador, 2)
    (mia,) = [c for c in e.clinicas if c.clinica_id == cid]
    assert mia.kek_versiones == {2}
    assert mia.en_rotacion
    assert f"Clínica {cid}: rotación de DEK en curso" in e.pendientes()

    # Sin la KEK v1 todo se sigue descifrando, y la rotación de DEK puede terminar.
    solo_v2 = _Keks({2: k2}, 2)
    async with AsyncSession(engine) as db:
        await membership.fijar_contexto(db, cid)
        cipher = await membership.cargar_cipher(db, solo_v2, cid)
        blob = (
            await db.execute(text("SELECT nombre FROM paciente WHERE id = :i"), {"i": pac})
        ).scalar_one()
        await db.commit()
    assert cipher.decrypt(bytes(blob), FieldContext("paciente", "nombre", cid, UUID(pac))) == (
        "Paciente Rotado"
    )
    await rotacion.rotar_dek_clinica(migrador, solo_v2, cid, espera=0)
    (mia,) = [c for c in (await rotacion.estado(migrador, 2)).clinicas if c.clinica_id == cid]
    assert not mia.en_rotacion

    async with AsyncSession(migrador) as db:
        (fila,) = (
            await db.execute(
                text(
                    "SELECT metadata FROM auditoria WHERE accion = 'kek_rotada' "
                    "AND metadata->>'reenvueltas' = '2' ORDER BY creado_en DESC LIMIT 1"
                )
            )
        ).all()
    assert fila.metadata["kek_version"] == 2


async def test_registro_cubre_todas_las_columnas_bytea(migrador: AsyncEngine) -> None:
    async with AsyncSession(migrador) as db:
        filas = (
            await db.execute(
                text(
                    "SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND data_type = 'bytea'"
                )
            )
        ).all()
    en_bd = {(f.table_name, f.column_name) for f in filas}
    registradas = (
        {(c.tabla, c.columna) for c in COLUMNAS_CLINICA}
        | set(COLUMNAS_PLATAFORMA)
        | set(BYTEA_NO_CIFRADAS)
    )
    assert en_bd == registradas


async def test_cli_estado(capsys: pytest.CaptureFixture[str]) -> None:
    assert await _correr(_argumentos(["estado"])) == 0
    salida = capsys.readouterr().out
    assert "KEK activa: v1" in salida
