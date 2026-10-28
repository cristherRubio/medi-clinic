"""Dependencias de FastAPI: BD, llaves, IP, sesión y CSRF."""

import hmac
import ipaddress
from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.auth.platform import PlatformCrypto, load_platform_crypto
from app.auth.sessions import SessionData, buscar, cookie_names, csrf_for
from app.config import Settings, get_settings
from app.crypto.keys import FileKeyProvider, KeyProvider
from app.db.session import make_engine


@lru_cache
def get_engine() -> AsyncEngine:
    return make_engine("app")


@lru_cache
def get_key_provider() -> KeyProvider:
    s = get_settings()
    return FileKeyProvider(s.secrets_dir, s.kek_active_version)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Sin commit automático: cada endpoint hace commit explícito."""
    async with AsyncSession(get_engine(), expire_on_commit=False) as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]
_platform: PlatformCrypto | None = None  # se carga una vez; rotar la DEK requiere reiniciar


async def get_platform(
    db: SessionDep, provider: Annotated[KeyProvider, Depends(get_key_provider)]
) -> PlatformCrypto:
    global _platform
    if _platform is None:
        _platform = await load_platform_crypto(db, provider)
    return _platform


PlatformDep = Annotated[PlatformCrypto, Depends(get_platform)]


def parse_ip(valor: str | None) -> str | None:
    if not valor:
        return None
    try:
        return str(ipaddress.ip_address(valor.split(",")[0].strip()))
    except ValueError:
        return None


def client_ip(request: Request, settings: Settings) -> str | None:
    if settings.ip_header:
        ip = parse_ip(request.headers.get(settings.ip_header))
        if ip:
            return ip
    return parse_ip(request.client.host if request.client else None)


async def sesion_actual(request: Request, db: SessionDep) -> SessionData:
    """Sesión vigente, incluso la intermedia (contraseña ok, falta TOTP)."""
    settings = get_settings()
    token = request.cookies.get(cookie_names(settings)[0])
    data = await buscar(db, token, settings) if token else None
    if data is None:
        raise HTTPException(401, "No autenticado")
    return data


async def sesion_completa(data: Annotated[SessionData, Depends(sesion_actual)]) -> SessionData:
    if not data.mfa_ok:
        raise HTTPException(401, "No autenticado")
    return data


async def verificar_csrf(
    request: Request,
    data: Annotated[SessionData, Depends(sesion_actual)],
    platform: PlatformDep,
) -> None:
    enviado = request.headers.get("X-CSRF-Token", "").encode()
    esperado = csrf_for(platform.csrf_key, data.token).encode()
    if not hmac.compare_digest(enviado, esperado):
        raise HTTPException(403, "CSRF inválido")
