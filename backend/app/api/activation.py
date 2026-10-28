"""Activación de invitación en dos pasos: contraseña + secreto TOTP, y confirmación con código."""

from typing import NoReturn
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import _poner_cookies
from app.api.deps import PlatformDep, SessionDep, client_ip
from app.auth import audit, sessions
from app.auth.passwords import PasswordPolicyError, hash_password
from app.auth.platform import PlatformCrypto
from app.auth.recovery import generate_recovery_codes, hash_code
from app.auth.throttle import clave_hash, esta_bloqueado, limpiar_fallos, registrar_fallo
from app.auth.tokens import hash_token
from app.auth.totp import new_totp_secret, provisioning_uri, verify_totp
from app.auth.totp_replay import consumir_paso
from app.config import Settings, get_settings

router = APIRouter(prefix="/api/auth/activar", tags=["auth"])

INVALIDA = "Invitación inválida o vencida"
BLOQUEADO = "Demasiados intentos. Intenta más tarde."


class IniciarIn(BaseModel):
    token: str = Field(min_length=20, max_length=100)
    password: str = Field(min_length=1, max_length=256)


class IniciarOut(BaseModel):
    totp_secret: str
    otpauth_uri: str


class ConfirmarIn(BaseModel):
    token: str = Field(min_length=20, max_length=100)
    codigo: str = Field(min_length=1, max_length=16)


class ConfirmarOut(BaseModel):
    codigos_recuperacion: list[str]


class _Ctx:
    def __init__(
        self, settings: Settings, ip: str | None, th: bytes, k_token: bytes, k_ip: bytes | None
    ) -> None:
        self.settings, self.ip, self.th, self.k_token, self.k_ip = settings, ip, th, k_token, k_ip


async def _preparar(
    db: AsyncSession, platform: PlatformCrypto, request: Request, token: str
) -> _Ctx:
    settings = get_settings()
    ip = client_ip(request, settings)
    th = hash_token(token)
    k_token = clave_hash(platform.throttle_key, "activar_token", th.hex())
    k_ip = clave_hash(platform.throttle_key, "activar_ip", ip) if ip else None
    if await esta_bloqueado(db, k_token, "activar_token") or (
        k_ip is not None and await esta_bloqueado(db, k_ip, "activar_ip")
    ):
        raise HTTPException(429, BLOQUEADO)
    return _Ctx(settings, ip, th, k_token, k_ip)


async def _fallo(db: AsyncSession, c: _Ctx, accion: str) -> NoReturn:
    await registrar_fallo(db, c.k_token, "activar_token")
    if c.k_ip is not None:
        await registrar_fallo(db, c.k_ip, "activar_ip")
    await audit.registrar(db, accion=accion, ip=c.ip)
    await db.commit()
    raise HTTPException(400, INVALIDA)


async def _invitacion(db: AsyncSession, th: bytes):  # type: ignore[no-untyped-def]
    return (
        await db.execute(
            text(
                "SELECT id, email, email_idx, rol FROM invitacion "
                "WHERE token_hash = :h AND usada_en IS NULL AND expira_en > now()"
            ),
            {"h": th},
        )
    ).first()


@router.post("/iniciar")
async def iniciar(
    body: IniciarIn, request: Request, db: SessionDep, platform: PlatformDep
) -> IniciarOut:
    c = await _preparar(db, platform, request, body.token)
    inv = await _invitacion(db, c.th)
    if inv is None:
        await _fallo(db, c, "activacion_invitacion_invalida")
    try:
        pwd_hash = hash_password(body.password)
    except PasswordPolicyError as e:
        raise HTTPException(422, str(e)) from None

    email = platform.cipher.decrypt(
        bytes(inv.email), platform.ctx("email", inv.id, tabla="invitacion")
    )
    previo = (
        await db.execute(
            text("SELECT id, activo, totp_activo FROM usuario WHERE email_idx = :i"),
            {"i": bytes(inv.email_idx)},
        )
    ).first()
    if previo is not None and (previo.activo or previo.totp_activo):
        # Cuenta ya activa (p. ej. invitación a otra clínica): llega en la Fase 1.
        await _fallo(db, c, "activacion_cuenta_existente")

    secreto = new_totp_secret()
    uid = previo.id if previo is not None else uuid4()
    cifrado = platform.cipher.encrypt(secreto, platform.ctx("totp_secret", uid))
    if previo is None:
        await db.execute(
            text(
                "INSERT INTO usuario (id, email, email_idx, password_hash, totp_secret, "
                "totp_activo, activo) VALUES (:i, :e, :x, :p, :t, false, false)"
            ),
            {
                "i": uid,
                "e": platform.cipher.encrypt(email, platform.ctx("email", uid)),
                "x": platform.email_idx(email),
                "p": pwd_hash,
                "t": cifrado,
            },
        )
    else:  # reintento de una activación a medias
        await db.execute(
            text("UPDATE usuario SET password_hash = :p, totp_secret = :t WHERE id = :i"),
            {"p": pwd_hash, "t": cifrado, "i": uid},
        )
    await audit.registrar(
        db,
        accion="activacion_iniciada",
        actor_usuario_id=uid,
        entidad="usuario",
        entidad_id=uid,
        ip=c.ip,
    )
    await db.commit()
    return IniciarOut(
        totp_secret=secreto,
        otpauth_uri=provisioning_uri(secreto, email, c.settings.app_name),
    )


@router.post("/confirmar")
async def confirmar(
    body: ConfirmarIn,
    request: Request,
    response: Response,
    db: SessionDep,
    platform: PlatformDep,
) -> ConfirmarOut:
    c = await _preparar(db, platform, request, body.token)
    inv = await _invitacion(db, c.th)
    if inv is None:
        await _fallo(db, c, "activacion_invitacion_invalida")
    usuario = (
        await db.execute(
            text(
                "SELECT id, totp_secret FROM usuario WHERE email_idx = :i "
                "AND NOT activo AND NOT totp_activo AND totp_secret IS NOT NULL"
            ),
            {"i": bytes(inv.email_idx)},
        )
    ).first()
    if usuario is None:
        await _fallo(db, c, "activacion_sin_inicio")

    secreto = platform.cipher.decrypt(
        bytes(usuario.totp_secret), platform.ctx("totp_secret", usuario.id)
    )
    paso = verify_totp(secreto, body.codigo)
    if paso is None or not await consumir_paso(db, usuario.id, paso):
        await _fallo(db, c, "activacion_totp_fallido")

    usada = (
        await db.execute(
            text(
                "UPDATE invitacion SET usada_en = now() "
                "WHERE id = :i AND usada_en IS NULL RETURNING id"
            ),
            {"i": inv.id},
        )
    ).first()
    if usada is None:  # otra petición la consumió primero
        await _fallo(db, c, "activacion_invitacion_invalida")

    await db.execute(
        text(
            "UPDATE usuario SET totp_activo = true, activo = true, ultimo_login = now() "
            "WHERE id = :i"
        ),
        {"i": usuario.id},
    )
    codigos = generate_recovery_codes()
    await db.execute(
        text("DELETE FROM codigo_recuperacion WHERE usuario_id = :u"), {"u": usuario.id}
    )
    for codigo in codigos:
        await db.execute(
            text("INSERT INTO codigo_recuperacion (usuario_id, codigo_hash) VALUES (:u, :h)"),
            {"u": usuario.id, "h": hash_code(codigo)},
        )
    token = await sessions.crear(db, usuario.id, mfa_ok=True, ip=c.ip, settings=c.settings)
    await limpiar_fallos(db, c.k_token, "activar_token")
    await audit.registrar(
        db,
        accion="activacion_ok",
        actor_usuario_id=usuario.id,
        entidad="usuario",
        entidad_id=usuario.id,
        ip=c.ip,
        metadata={"rol": inv.rol},
    )
    await db.commit()
    _poner_cookies(response, c.settings, platform, token, mfa_ok=True)
    return ConfirmarOut(codigos_recuperacion=codigos)
