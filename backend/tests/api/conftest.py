import os
from collections.abc import AsyncIterator, Iterator
from typing import NamedTuple
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from app.api.deps import get_key_provider, get_platform, get_session
from app.api.operator import get_operador_session
from app.auth import membership, sessions
from app.auth.passwords import hash_password
from app.auth.platform import PlatformCrypto
from app.auth.sessions import cookie_names, csrf_for
from app.auth.tokens import hash_token, new_token
from app.auth.totp import new_totp_secret
from app.config import get_settings
from app.crypto.envelope import generate_dek, wrap_dek
from app.crypto.keys import KeyProvider
from app.db.session import make_engine
from app.main import create_app
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from starlette.testclient import TestClient

PASSWORD = "clave-de-prueba-larga"


class _Provider(KeyProvider):
    """KEK en memoria para pruebas."""

    def __init__(self) -> None:
        self._kek = os.urandom(32)

    @property
    def active_version(self) -> int:
        return 1

    def get_kek(self, version: int) -> bytes:
        return self._kek


class Cuenta(NamedTuple):
    id: UUID
    email: str
    totp_secret: str | None


class Invitacion(NamedTuple):
    token: str
    email: str
    clinica_id: UUID


@pytest.fixture
def platform() -> PlatformCrypto:
    return PlatformCrypto({1: generate_dek()}, 1, os.urandom(32))


@pytest.fixture
def provider() -> KeyProvider:
    return _Provider()


def _cliente(platform: PlatformCrypto, provider: KeyProvider) -> Iterator[TestClient]:
    async def _session() -> AsyncIterator[AsyncSession]:
        engine = make_engine("app")  # uno por petición: evita mezclar bucles de eventos
        try:
            async with AsyncSession(engine, expire_on_commit=False) as s:
                yield s
        finally:
            await engine.dispose()

    async def _session_operador() -> AsyncIterator[AsyncSession]:
        engine = make_engine("operador")
        try:
            async with AsyncSession(engine, expire_on_commit=False) as s:
                yield s
        finally:
            await engine.dispose()

    app = create_app()
    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_operador_session] = _session_operador
    app.dependency_overrides[get_platform] = lambda: platform
    app.dependency_overrides[get_key_provider] = lambda: provider
    with TestClient(app) as c:
        yield c


@pytest.fixture
def client(platform: PlatformCrypto, provider: KeyProvider) -> Iterator[TestClient]:
    yield from _cliente(platform, provider)


@pytest.fixture
def otro_client(platform: PlatformCrypto, provider: KeyProvider) -> Iterator[TestClient]:
    """Segundo cliente con sus propias cookies (p. ej. operador + admin a la vez)."""
    yield from _cliente(platform, provider)


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    e = make_engine("app")
    yield e
    await e.dispose()


async def crear_usuario(
    engine: AsyncEngine,
    platform: PlatformCrypto,
    *,
    totp: bool = False,
    operador: bool = False,
) -> Cuenta:
    uid = uuid4()
    email = f"{uid.hex}@prueba.invalid"
    secreto = new_totp_secret() if totp else None
    async with AsyncSession(engine) as s:
        await s.execute(
            text(
                "INSERT INTO usuario (id, email, email_idx, password_hash, totp_secret, "
                "totp_activo, es_operador) VALUES (:i, :e, :x, :p, :t, :a, :o)"
            ),
            {
                "i": uid,
                "e": platform.cipher.encrypt(email, platform.ctx("email", uid)),
                "x": platform.email_idx(email),
                "p": hash_password(PASSWORD),
                "t": platform.cipher.encrypt(secreto, platform.ctx("totp_secret", uid))
                if secreto
                else None,
                "a": totp,
                "o": operador,
            },
        )
        await s.commit()
    return Cuenta(uid, email, secreto)


async def crear_clinica(provider: KeyProvider) -> UUID:
    """Alta por el motor `operador` (única vía). Con DEK real, para poder cifrar personal."""
    cid, dek = uuid4(), generate_dek()
    e = make_engine("operador")
    try:
        async with e.begin() as c:
            await c.execute(
                text(
                    "INSERT INTO clinica (id, nombre, tipo_persona, nombre_legal, rfc, "
                    "representante_nombre, representante_curp, dek_wrapped, dek_version) "
                    "VALUES (:id, 'test', 'fisica', 'test', :x, :x, :x, :w, 1)"
                ),
                {"id": cid, "x": b"x", "w": wrap_dek(provider, dek, f"clinica|{cid}|v1")},
            )
    finally:
        await e.dispose()
    return cid


async def crear_invitacion_completa(
    engine: AsyncEngine,
    platform: PlatformCrypto,
    provider: KeyProvider,
    *,
    horas: int = 72,
    rol: str = "admin",
    email: str | None = None,
    clinica_id: UUID | None = None,
) -> Invitacion:
    """`horas` negativas = ya vencida. `email` permite invitar a un usuario existente."""
    iid = uuid4()
    email = email or f"{iid.hex}@prueba.invalid"
    cid = clinica_id or await crear_clinica(provider)
    token = new_token()
    async with AsyncSession(engine) as s:
        await s.execute(
            text(
                "INSERT INTO invitacion (id, email, email_idx, clinica_id, rol, token_hash, "
                "expira_en) VALUES (:i, :e, :x, :c, :r, :h, now() + make_interval(hours => :hr))"
            ),
            {
                "i": iid,
                "e": platform.cipher.encrypt(email, platform.ctx("email", iid, tabla="invitacion")),
                "x": platform.email_idx(email),
                "c": cid,
                "r": rol,
                "h": hash_token(token),
                "hr": horas,
            },
        )
        await s.commit()
    return Invitacion(token, email, cid)


async def crear_invitacion(
    engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider, *, horas: int = 72
) -> tuple[str, str]:
    """Devuelve (token en claro, email)."""
    inv = await crear_invitacion_completa(engine, platform, provider, horas=horas)
    return inv.token, inv.email


class Miembro(NamedTuple):
    uid: UUID
    pid: UUID
    email: str


async def crear_personal(
    engine: AsyncEngine,
    provider: KeyProvider,
    cid: UUID,
    uid: UUID,
    rol: str,
    nombre: str = "Prueba",
) -> UUID:
    async with AsyncSession(engine) as s:
        pid = await membership.crear_personal(
            s, provider, clinica_id=cid, usuario_id=uid, rol=rol, nombre=nombre
        )
        await s.commit()
    return pid


async def crear_equipo(
    engine: AsyncEngine, platform: PlatformCrypto, provider: KeyProvider, *roles: str
) -> tuple[UUID, list[Miembro]]:
    """Clínica nueva con una persona por rol (nombres 'Persona 0', 'Persona 1'...)."""
    cid = await crear_clinica(provider)
    miembros = []
    for i, rol in enumerate(roles):
        u = await crear_usuario(engine, platform)
        pid = await crear_personal(engine, provider, cid, u.id, rol, f"Persona {i}")
        miembros.append(Miembro(u.id, pid, u.email))
    return cid, miembros


async def como(
    c: TestClient, engine: AsyncEngine, platform: PlatformCrypto, cid: UUID, m: Miembro
) -> dict[str, str]:
    """Abre sesión de `m` en el cliente `c` y devuelve la cabecera CSRF."""
    settings = get_settings()
    async with AsyncSession(engine) as s:
        token = await sessions.crear(
            s, m.uid, mfa_ok=True, ip=None, settings=settings, clinica_id=cid, personal_id=m.pid
        )
        await s.commit()
    c.cookies.set(cookie_names(settings)[0], token)
    return {"X-CSRF-Token": csrf_for(platform.csrf_key, token)}
