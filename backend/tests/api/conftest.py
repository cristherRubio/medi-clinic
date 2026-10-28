import os
from collections.abc import AsyncIterator, Iterator
from typing import NamedTuple
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from app.api.deps import get_platform, get_session
from app.auth.passwords import hash_password
from app.auth.platform import PlatformCrypto
from app.auth.tokens import hash_token, new_token
from app.auth.totp import new_totp_secret
from app.crypto.envelope import generate_dek
from app.db.session import make_engine
from app.main import create_app
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from starlette.testclient import TestClient

PASSWORD = "clave-de-prueba-larga"


class Cuenta(NamedTuple):
    id: UUID
    email: str
    totp_secret: str | None


@pytest.fixture
def platform() -> PlatformCrypto:
    return PlatformCrypto({1: generate_dek()}, 1, os.urandom(32))


@pytest.fixture
def client(platform: PlatformCrypto) -> Iterator[TestClient]:
    async def _session() -> AsyncIterator[AsyncSession]:
        engine = make_engine("app")  # uno por petición: evita mezclar bucles de eventos
        try:
            async with AsyncSession(engine, expire_on_commit=False) as s:
                yield s
        finally:
            await engine.dispose()

    app = create_app()
    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_platform] = lambda: platform
    with TestClient(app) as c:
        yield c


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


async def crear_invitacion(
    engine: AsyncEngine, platform: PlatformCrypto, *, horas: int = 72
) -> tuple[str, str]:
    """Devuelve (token en claro, email). `horas` negativas = ya vencida."""
    iid = uuid4()
    email = f"{iid.hex}@prueba.invalid"
    token = new_token()
    async with AsyncSession(engine) as s:
        await s.execute(
            text(
                "INSERT INTO invitacion (id, email, email_idx, rol, token_hash, expira_en) "
                "VALUES (:i, :e, :x, 'admin', :h, now() + make_interval(hours => :hr))"
            ),
            {
                "i": iid,
                "e": platform.cipher.encrypt(email, platform.ctx("email", iid, tabla="invitacion")),
                "x": platform.email_idx(email),
                "h": hash_token(token),
                "hr": horas,
            },
        )
        await s.commit()
    return token, email
