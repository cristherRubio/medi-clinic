"""Endpoints de autenticación: login en dos pasos, logout y /me."""

from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    PlatformDep,
    SessionDep,
    client_ip,
    sesion_actual,
    sesion_completa,
    verificar_csrf,
)
from app.auth import audit, sessions
from app.auth.passwords import hash_password, needs_rehash, verify_dummy, verify_password
from app.auth.platform import PlatformCrypto
from app.auth.sessions import SessionData, cookie_names, csrf_for
from app.auth.throttle import clave_hash, esta_bloqueado, limpiar_fallos, registrar_fallo
from app.auth.totp import verify_totp
from app.auth.totp_replay import consumir_paso
from app.config import Settings, get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])

BLOQUEADO = "Demasiados intentos. Intenta más tarde."


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class TotpIn(BaseModel):
    codigo: str = Field(min_length=1, max_length=16)


class LoginOut(BaseModel):
    mfa_requerida: bool


class MeOut(BaseModel):
    id: UUID
    email: str
    es_operador: bool
    totp_activo: bool


def _claves(
    platform: PlatformCrypto, email_idx: bytes, ip: str | None
) -> tuple[bytes, bytes | None]:
    # Sin IP determinable no se limita por IP (evita un cubo compartido por todos).
    cuenta = clave_hash(platform.throttle_key, "login_cuenta", email_idx.hex())
    por_ip = clave_hash(platform.throttle_key, "login_ip", ip) if ip else None
    return cuenta, por_ip


async def _bloqueado(db: AsyncSession, cuenta: bytes, por_ip: bytes | None) -> bool:
    if await esta_bloqueado(db, cuenta, "login_cuenta"):
        return True
    return por_ip is not None and await esta_bloqueado(db, por_ip, "login_ip")


async def _fallar(
    db: AsyncSession,
    cuenta: bytes,
    por_ip: bytes | None,
    ip: str | None,
    usuario_id: UUID | None,
    accion: str,
) -> NoReturn:
    await registrar_fallo(db, cuenta, "login_cuenta")
    if por_ip is not None:
        await registrar_fallo(db, por_ip, "login_ip")
    await audit.registrar(db, accion=accion, actor_usuario_id=usuario_id, ip=ip)
    await db.commit()  # el fallo se guarda aunque se responda con error
    raise HTTPException(401, "Credenciales inválidas")


def _poner_cookies(
    response: Response, settings: Settings, platform: PlatformCrypto, token: str, mfa_ok: bool
) -> None:
    sid, csrf = cookie_names(settings)
    max_age = settings.session_max_hours * 3600 if mfa_ok else settings.sesion_pendiente_min * 60
    comunes = {"max_age": max_age, "secure": settings.cookie_secure, "samesite": "lax", "path": "/"}
    response.set_cookie(sid, token, httponly=True, **comunes)  # type: ignore[arg-type]
    response.set_cookie(
        csrf,
        csrf_for(platform.csrf_key, token),
        httponly=False,
        **comunes,  # type: ignore[arg-type]
    )


@router.post("/login")
async def login(
    body: LoginIn, request: Request, response: Response, db: SessionDep, platform: PlatformDep
) -> LoginOut:
    settings = get_settings()
    ip = client_ip(request, settings)
    idx = platform.email_idx(body.email)
    cuenta, por_ip = _claves(platform, idx, ip)
    if await _bloqueado(db, cuenta, por_ip):
        raise HTTPException(429, BLOQUEADO)

    row = (
        await db.execute(
            text(
                "SELECT id, password_hash, totp_activo, es_operador, activo "
                "FROM usuario WHERE email_idx = :i"
            ),
            {"i": idx},
        )
    ).first()
    if row is None or row.password_hash is None:
        verify_dummy(body.password)  # mismo costo que una cuenta real
        await _fallar(db, cuenta, por_ip, ip, None, "login_fallido")
    if (
        not verify_password(body.password, row.password_hash)
        or not row.activo
        or (row.es_operador and not row.totp_activo)  # el operador exige 2FA
    ):
        await _fallar(db, cuenta, por_ip, ip, row.id, "login_fallido")

    await limpiar_fallos(db, cuenta, "login_cuenta")  # los de la IP se conservan
    if needs_rehash(row.password_hash):
        await db.execute(
            text("UPDATE usuario SET password_hash = :h WHERE id = :i"),
            {"h": hash_password(body.password), "i": row.id},
        )
    mfa = bool(row.totp_activo)
    token = await sessions.crear(db, row.id, mfa_ok=not mfa, ip=ip, settings=settings)
    if not mfa:
        await db.execute(
            text("UPDATE usuario SET ultimo_login = now() WHERE id = :i"), {"i": row.id}
        )
    await audit.registrar(
        db,
        accion="login_password_ok" if mfa else "login_ok",
        actor_usuario_id=row.id,
        entidad="usuario",
        entidad_id=row.id,
        ip=ip,
    )
    await db.commit()
    _poner_cookies(response, settings, platform, token, mfa_ok=not mfa)
    return LoginOut(mfa_requerida=mfa)


@router.post("/login/totp", dependencies=[Depends(verificar_csrf)])
async def login_totp(
    body: TotpIn,
    request: Request,
    response: Response,
    db: SessionDep,
    platform: PlatformDep,
    data: Annotated[SessionData, Depends(sesion_actual)],
) -> LoginOut:
    if data.mfa_ok:
        raise HTTPException(400, "La sesión ya está verificada")
    settings = get_settings()
    ip = client_ip(request, settings)
    row = (
        await db.execute(
            text("SELECT email_idx, totp_secret FROM usuario WHERE id = :i"),
            {"i": data.usuario_id},
        )
    ).one()
    cuenta, por_ip = _claves(platform, bytes(row.email_idx), ip)
    if await _bloqueado(db, cuenta, por_ip):
        raise HTTPException(429, BLOQUEADO)

    paso = None
    if row.totp_secret is not None:
        secreto = platform.cipher.decrypt(
            bytes(row.totp_secret), platform.ctx("totp_secret", data.usuario_id)
        )
        paso = verify_totp(secreto, body.codigo)
    if paso is None or not await consumir_paso(db, data.usuario_id, paso):
        await _fallar(db, cuenta, por_ip, ip, data.usuario_id, "login_totp_fallido")

    await limpiar_fallos(db, cuenta, "login_cuenta")
    await sessions.borrar(db, data.id)  # nueva sesión al subir de nivel
    token = await sessions.crear(db, data.usuario_id, mfa_ok=True, ip=ip, settings=settings)
    await db.execute(
        text("UPDATE usuario SET ultimo_login = now() WHERE id = :i"), {"i": data.usuario_id}
    )
    await audit.registrar(
        db,
        accion="login_ok",
        actor_usuario_id=data.usuario_id,
        entidad="usuario",
        entidad_id=data.usuario_id,
        ip=ip,
    )
    await db.commit()
    _poner_cookies(response, settings, platform, token, mfa_ok=True)
    return LoginOut(mfa_requerida=False)


@router.post("/logout", status_code=204, dependencies=[Depends(verificar_csrf)])
async def logout(
    request: Request, db: SessionDep, data: Annotated[SessionData, Depends(sesion_actual)]
) -> Response:
    settings = get_settings()
    await sessions.borrar(db, data.id)
    await audit.registrar(
        db,
        accion="logout",
        actor_usuario_id=data.usuario_id,
        entidad="usuario",
        entidad_id=data.usuario_id,
        ip=client_ip(request, settings),
    )
    await db.commit()
    respuesta = Response(status_code=204)
    for nombre in cookie_names(settings):
        respuesta.delete_cookie(nombre, path="/", secure=settings.cookie_secure, samesite="lax")
    return respuesta


@router.get("/me")
async def me(
    db: SessionDep, platform: PlatformDep, data: Annotated[SessionData, Depends(sesion_completa)]
) -> MeOut:
    row = (
        await db.execute(
            text("SELECT email, es_operador, totp_activo FROM usuario WHERE id = :i"),
            {"i": data.usuario_id},
        )
    ).one()
    await db.commit()  # persiste el ultimo_uso de la sesión
    return MeOut(
        id=data.usuario_id,
        email=platform.cipher.decrypt(bytes(row.email), platform.ctx("email", data.usuario_id)),
        es_operador=row.es_operador,
        totp_activo=row.totp_activo,
    )
