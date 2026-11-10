"""Dependencia `requerir`: rol, contexto, CSRF, sesión intermedia, personal inactivo, suspensión."""

import os
from uuid import UUID

import pytest
from app.api.authz import Actor, requerir
from app.api.deps import SessionDep
from app.auth import membership, sessions
from app.auth.platform import PlatformCrypto
from app.auth.rbac import Accion
from app.auth.sessions import cookie_names, csrf_for
from app.config import get_settings
from app.crypto.keys import KeyProvider
from app.db.session import make_engine
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from starlette.testclient import TestClient

from .conftest import crear_clinica, crear_usuario

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.environ.get("APP_TEST_DB") != "1",
        reason="Pruebas de BD: solo en CI (APP_TEST_DB=1)",
    ),
]


@pytest.fixture
def app_prueba(client: TestClient) -> TestClient:
    router = APIRouter(prefix="/_t")

    @router.get("/ver")
    async def ver(
        actor: Actor = Depends(requerir(Accion.VER_PACIENTES)),  # noqa: B008
    ) -> dict[str, str]:
        return {"rol": actor.rol, "alcance": actor.alcance}

    @router.post("/borrar")
    async def borrar(
        db: SessionDep,
        actor: Actor = Depends(requerir(Accion.BORRAR)),  # noqa: B008
    ) -> dict[str, str]:
        return {"rol": actor.rol}

    client.app.include_router(router)  # type: ignore[attr-defined]
    return client


async def _personal(
    engine: AsyncEngine,
    platform: PlatformCrypto,
    provider: KeyProvider,
    cid: UUID,
    uid: UUID,
    rol: str,
) -> UUID:
    async with AsyncSession(engine) as s:
        pid = await membership.crear_personal(
            s, provider, clinica_id=cid, usuario_id=uid, rol=rol, nombre="Prueba"
        )
        await s.commit()
    return pid


async def _entrar(
    c: TestClient,
    engine: AsyncEngine,
    platform: PlatformCrypto,
    usuario_id: UUID,
    *,
    mfa_ok: bool = True,
    clinica_id: UUID | None = None,
    personal_id: UUID | None = None,
) -> str:
    settings = get_settings()
    async with AsyncSession(engine) as s:
        token = await sessions.crear(
            s,
            usuario_id,
            mfa_ok=mfa_ok,
            ip=None,
            settings=settings,
            clinica_id=clinica_id,
            personal_id=personal_id,
        )
        await s.commit()
    c.cookies.set(cookie_names(settings)[0], token)
    return csrf_for(platform.csrf_key, token)


async def _rol_en_clinica(
    c: TestClient,
    engine: AsyncEngine,
    platform: PlatformCrypto,
    provider: KeyProvider,
    rol: str,
) -> tuple[str, UUID, UUID, UUID]:
    cid = await crear_clinica(provider)
    cuenta = await crear_usuario(engine, platform)
    pid = await _personal(engine, platform, provider, cid, cuenta.id, rol)
    csrf = await _entrar(c, engine, platform, cuenta.id, clinica_id=cid, personal_id=pid)
    return csrf, cid, pid, cuenta.id


@pytest.mark.parametrize(
    ("rol", "alcance", "borra"),
    [("admin", "todos", 200), ("asistente", "todos", 403), ("medico", "propios", 403)],
)
async def test_roles(
    app_prueba: TestClient,
    engine: AsyncEngine,
    platform: PlatformCrypto,
    provider: KeyProvider,
    rol: str,
    alcance: str,
    borra: int,
) -> None:
    csrf, *_ = await _rol_en_clinica(app_prueba, engine, platform, provider, rol)
    r = app_prueba.get("/_t/ver")
    assert r.status_code == 200
    assert r.json() == {"rol": rol, "alcance": alcance}
    assert app_prueba.post("/_t/borrar", headers={"X-CSRF-Token": csrf}).status_code == borra


async def test_mutacion_exige_csrf(
    app_prueba: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    await _rol_en_clinica(app_prueba, engine, platform, provider, "admin")
    assert app_prueba.post("/_t/borrar").status_code == 403
    assert app_prueba.post("/_t/borrar", headers={"X-CSRF-Token": "x"}).status_code == 403


async def test_sin_sesion(app_prueba: TestClient) -> None:
    assert app_prueba.get("/_t/ver").status_code == 401


async def test_sesion_intermedia(
    app_prueba: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    cid = await crear_clinica(provider)
    cuenta = await crear_usuario(engine, platform)
    pid = await _personal(engine, platform, provider, cid, cuenta.id, "admin")
    await _entrar(
        app_prueba, engine, platform, cuenta.id, mfa_ok=False, clinica_id=cid, personal_id=pid
    )
    assert app_prueba.get("/_t/ver").status_code == 401


async def test_operador_y_sin_contexto_dan_404(
    app_prueba: TestClient, engine: AsyncEngine, platform: PlatformCrypto
) -> None:
    op = await crear_usuario(engine, platform, totp=True, operador=True)
    await _entrar(app_prueba, engine, platform, op.id)
    assert app_prueba.get("/_t/ver").status_code == 404


async def test_personal_inactivo_404(
    app_prueba: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    _, cid, pid, _ = await _rol_en_clinica(app_prueba, engine, platform, provider, "admin")
    async with AsyncSession(engine) as s:
        await membership.fijar_contexto(s, cid)
        await s.execute(text("UPDATE personal SET activo = false WHERE id = :p"), {"p": pid})
        await s.commit()
    assert app_prueba.get("/_t/ver").status_code == 404


async def test_clinica_suspendida_404(
    app_prueba: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    _, cid, _, _ = await _rol_en_clinica(app_prueba, engine, platform, provider, "admin")
    op = make_engine("operador")
    try:
        async with op.begin() as c:
            await c.execute(
                text("UPDATE clinica SET estado = 'suspendida' WHERE id = :c"), {"c": cid}
            )
    finally:
        await op.dispose()
    assert app_prueba.get("/_t/ver").status_code == 404


async def test_personal_ajeno_404(
    app_prueba: TestClient, engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider
) -> None:
    """Sesión de B apuntando al personal de A (misma clínica): no debe valer."""
    cid = await crear_clinica(provider)
    a = await crear_usuario(engine, platform)
    pid_a = await _personal(engine, platform, provider, cid, a.id, "admin")
    b = await crear_usuario(engine, platform)
    await _personal(engine, platform, provider, cid, b.id, "asistente")
    await _entrar(app_prueba, engine, platform, b.id, clinica_id=cid, personal_id=pid_a)
    assert app_prueba.get("/_t/ver").status_code == 404
