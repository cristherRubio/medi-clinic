"""Restablecimiento de contraseña por correo (sin revelar si la cuenta existe).

1. `POST /api/auth/contrasena/olvide {email}` → siempre 202. Si la cuenta existe, está
   activa, hay proveedor de correo y no se pasó el límite por cuenta, crea un token de un
   solo uso y manda el enlace **después de responder** (el tiempo de respuesta no delata
   la cuenta). Sin proveedor (`ninguno`) no se envía nada.
2. `POST /api/auth/contrasena/restablecer {token, password, codigo?}` → si la cuenta tiene
   TOTP exige un código TOTP o de recuperación (el correo solo no basta). Cambia la
   contraseña, consume el token, cierra todas las sesiones del usuario y no inicia sesión.
"""

import logging
from typing import Annotated, Any, NoReturn

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PlatformDep, SessionDep, client_ip
from app.auth import audit
from app.auth.passwords import PasswordPolicyError, hash_password
from app.auth.platform import PlatformCrypto
from app.auth.recovery import hash_code
from app.auth.throttle import clave_hash, esta_bloqueado, limpiar_fallos, registrar_fallo
from app.auth.tokens import hash_token, new_token
from app.auth.totp import verify_totp
from app.auth.totp_replay import consumir_paso
from app.config import get_settings
from app.correo import Correo, CorreoError, EmailProvider, get_correo, restablecimiento

router = APIRouter(prefix="/api/auth/contrasena", tags=["auth"])
log = logging.getLogger(__name__)

CorreoDep = Annotated[EmailProvider, Depends(get_correo)]

BLOQUEADO = "Demasiados intentos. Intenta más tarde."
INVALIDO = "El enlace no es válido o ya venció"
CODIGO_INVALIDO = "Código inválido"
ACEPTADO = "Si la cuenta existe, enviamos un correo con instrucciones"


class OlvideIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class OlvideOut(BaseModel):
    detail: str


class RestablecerIn(BaseModel):
    token: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)
    codigo: str | None = Field(default=None, max_length=32)  # TOTP o de recuperación


async def _enviar(proveedor: EmailProvider, correo: Correo) -> None:
    """Tarea en segundo plano: un fallo se registra sin destinatario ni enlace."""
    try:
        await proveedor.enviar(correo)
    except CorreoError as e:
        log.warning("No se pudo enviar el correo de restablecimiento: %s", e)


@router.post("/olvide", status_code=202)
async def olvide(
    body: OlvideIn,
    request: Request,
    tareas: BackgroundTasks,
    db: SessionDep,
    platform: PlatformDep,
    correo: CorreoDep,
) -> OlvideOut:
    settings = get_settings()
    ip = client_ip(request, settings)
    if ip:
        k_ip = clave_hash(platform.throttle_key, "olvide_ip", ip)
        if await esta_bloqueado(db, k_ip, "olvide_ip"):
            raise HTTPException(429, BLOQUEADO)
        await registrar_fallo(db, k_ip, "olvide_ip")  # cuenta cada solicitud
    idx = platform.email_idx(body.email)
    k_cuenta = clave_hash(platform.throttle_key, "olvide_cuenta", idx.hex())
    excedida = await esta_bloqueado(db, k_cuenta, "olvide_cuenta")
    await registrar_fallo(db, k_cuenta, "olvide_cuenta")

    row = (
        await db.execute(
            text("SELECT id, email FROM usuario WHERE email_idx = :x AND activo"), {"x": idx}
        )
    ).first()
    if row is None or excedida or not correo.activo:
        await audit.registrar(
            db,
            accion="restablecimiento_no_enviado",
            actor_usuario_id=row.id if row is not None else None,
            ip=ip,
            metadata={"motivo": "límite" if excedida else "sin_correo" if row else "sin_cuenta"},
        )
        await db.commit()
        return OlvideOut(detail=ACEPTADO)

    token = new_token()
    await db.execute(
        text(
            "UPDATE restablecimiento SET usado_en = now() "
            "WHERE usuario_id = :u AND usado_en IS NULL"
        ),
        {"u": row.id},
    )
    await db.execute(
        text(
            "INSERT INTO restablecimiento (usuario_id, token_hash, expira_en) "
            "VALUES (:u, :h, now() + make_interval(mins => :m))"
        ),
        {"u": row.id, "h": hash_token(token), "m": settings.restablecer_minutos},
    )
    await audit.registrar(
        db,
        accion="restablecimiento_solicitado",
        actor_usuario_id=row.id,
        entidad="usuario",
        entidad_id=row.id,
        ip=ip,
    )
    await db.commit()
    email = platform.cipher.decrypt(bytes(row.email), platform.ctx("email", row.id))
    tareas.add_task(
        _enviar, correo, restablecimiento(settings, email, token, settings.restablecer_minutos)
    )
    return OlvideOut(detail=ACEPTADO)


async def _fallo(
    db: AsyncSession, k_ip: bytes | None, k_token: bytes, ip: str | None, accion: str, msg: str
) -> NoReturn:
    if k_ip is not None:
        await registrar_fallo(db, k_ip, "restablecer_ip")
    await registrar_fallo(db, k_token, "restablecer_token")
    await audit.registrar(db, accion=accion, ip=ip)
    await db.commit()
    raise HTTPException(400, msg)


async def _codigo_valido(
    db: AsyncSession, platform: PlatformCrypto, r: Row[Any], codigo: str
) -> bool:
    """TOTP (sin reutilizar el paso) o un código de recuperación (se consume)."""
    if r.totp_secret is not None:
        secreto = platform.cipher.decrypt(
            bytes(r.totp_secret), platform.ctx("totp_secret", r.usuario_id)
        )
        paso = verify_totp(secreto, codigo)
        if paso is not None and await consumir_paso(db, r.usuario_id, paso):
            return True
    usado = (
        await db.execute(
            text(
                "UPDATE codigo_recuperacion SET usado_en = now() "
                "WHERE usuario_id = :u AND codigo_hash = :h AND usado_en IS NULL RETURNING id"
            ),
            {"u": r.usuario_id, "h": hash_code(codigo)},
        )
    ).first()
    return usado is not None


@router.post("/restablecer", status_code=204)
async def restablecer(
    body: RestablecerIn, request: Request, db: SessionDep, platform: PlatformDep
) -> None:
    settings = get_settings()
    ip = client_ip(request, settings)
    th = hash_token(body.token)
    k_token = clave_hash(platform.throttle_key, "restablecer_token", th.hex())
    k_ip = clave_hash(platform.throttle_key, "restablecer_ip", ip) if ip else None
    if await esta_bloqueado(db, k_token, "restablecer_token") or (
        k_ip is not None and await esta_bloqueado(db, k_ip, "restablecer_ip")
    ):
        raise HTTPException(429, BLOQUEADO)

    r = (
        await db.execute(
            text(
                "SELECT r.id, r.usuario_id, u.totp_activo, u.totp_secret, u.email_idx "
                "FROM restablecimiento r JOIN usuario u ON u.id = r.usuario_id "
                "WHERE r.token_hash = :h AND r.usado_en IS NULL AND r.expira_en > now() "
                "AND u.activo FOR UPDATE OF r"
            ),
            {"h": th},
        )
    ).first()
    if r is None:
        await _fallo(db, k_ip, k_token, ip, "restablecimiento_invalido", INVALIDO)
    try:
        nuevo_hash = hash_password(body.password)
    except PasswordPolicyError as e:
        raise HTTPException(422, str(e)) from None
    if r.totp_activo:
        if not body.codigo:
            raise HTTPException(422, "Escribe el código de tu app de autenticación")
        if not await _codigo_valido(db, platform, r, body.codigo.strip()):
            await _fallo(db, k_ip, k_token, ip, "restablecimiento_codigo_fallido", CODIGO_INVALIDO)

    uid = r.usuario_id
    await db.execute(
        text("UPDATE usuario SET password_hash = :p WHERE id = :u"), {"p": nuevo_hash, "u": uid}
    )
    await db.execute(
        text(
            "UPDATE restablecimiento SET usado_en = now() "
            "WHERE usuario_id = :u AND usado_en IS NULL"
        ),
        {"u": uid},
    )
    await db.execute(text("DELETE FROM sesion WHERE usuario_id = :u"), {"u": uid})
    cuenta = clave_hash(platform.throttle_key, "login_cuenta", bytes(r.email_idx).hex())
    await limpiar_fallos(db, cuenta, "login_cuenta")  # la cuenta deja de estar bloqueada
    await limpiar_fallos(db, k_token, "restablecer_token")
    await audit.registrar(
        db,
        accion="contrasena_restablecida",
        actor_usuario_id=uid,
        entidad="usuario",
        entidad_id=uid,
        ip=ip,
        metadata={"segundo_factor": bool(r.totp_activo)},
    )
    await db.commit()
