"""Panel del operador: clínicas e invitaciones. No toca datos de pacientes ni de personal."""

from collections.abc import AsyncIterator
from datetime import date, datetime
from functools import lru_cache
from typing import Annotated, Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.api.deps import (
    PlatformDep,
    SessionDep,
    client_ip,
    get_key_provider,
    sesion_completa,
    verificar_csrf,
)
from app.auth import audit
from app.auth.platform import PlatformCrypto
from app.auth.sessions import SessionData
from app.auth.tokens import hash_token, new_token
from app.config import get_settings
from app.crypto.envelope import generate_dek, wrap_dek
from app.crypto.fields import FieldCipher, FieldContext
from app.crypto.keys import KeyProvider
from app.db.session import make_engine

DEK_VERSION = 1
Plan = Literal["p5", "p10", "p20", "p50", "custom"]
Estado = Literal["prueba", "activa", "suspendida"]


@lru_cache
def get_operador_engine() -> AsyncEngine:
    return make_engine("operador")


async def get_operador_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSession(get_operador_engine(), expire_on_commit=False) as s:
        yield s


async def exigir_operador(
    db: SessionDep, data: Annotated[SessionData, Depends(sesion_completa)]
) -> SessionData:
    """Sesión completa (con TOTP) de un operador. Para cualquier otro: 404 uniforme."""
    es_op = (
        await db.execute(
            text("SELECT es_operador FROM usuario WHERE id = :i"), {"i": data.usuario_id}
        )
    ).scalar_one()
    if not es_op:
        raise HTTPException(404, "No encontrado")
    return data


OpDb = Annotated[AsyncSession, Depends(get_operador_session)]
OperadorDep = Annotated[SessionData, Depends(exigir_operador)]
ProviderDep = Annotated[KeyProvider, Depends(get_key_provider)]

router = APIRouter(
    prefix="/api/operador", tags=["operador"], dependencies=[Depends(exigir_operador)]
)
CSRF = [Depends(verificar_csrf)]


class ClinicaIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    tipo_persona: Literal["fisica", "moral"]
    nombre_legal: str = Field(min_length=1, max_length=200)
    rfc: str = Field(min_length=12, max_length=13)
    representante_nombre: str = Field(min_length=1, max_length=200)
    representante_curp: str = Field(min_length=18, max_length=18)
    zona_horaria: str = "America/Mexico_City"
    plan: Plan = "p5"
    vigencia_hasta: date | None = None
    email_admin: str = Field(min_length=3, max_length=254)


class ClinicaCreada(BaseModel):
    clinica_id: UUID
    invitacion_id: UUID
    token: str  # se muestra una sola vez; el operador arma y envía el enlace
    expira_en: datetime


class ClinicaOut(BaseModel):
    id: UUID
    nombre: str
    plan: str
    estado: str
    vigencia_hasta: date | None
    notificaciones_whatsapp: bool
    creado_en: datetime


class ClinicaPatch(BaseModel):
    plan: Plan | None = None
    estado: Estado | None = None
    vigencia_hasta: date | None = None
    notificaciones_whatsapp: bool | None = None


class InvitacionOut(BaseModel):
    id: UUID
    rol: str
    expira_en: datetime
    usada_en: datetime | None


class ExtenderIn(BaseModel):
    horas: int = Field(ge=1, le=720)


@router.post("/clinicas", status_code=201, dependencies=CSRF)
async def crear_clinica(
    body: ClinicaIn,
    request: Request,
    db: OpDb,
    op: OperadorDep,
    platform: PlatformDep,
    provider: ProviderDep,
) -> ClinicaCreada:
    settings = get_settings()
    try:
        ZoneInfo(body.zona_horaria)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise HTTPException(422, "Zona horaria inválida") from None

    cid = uuid4()
    dek = generate_dek()
    cipher = FieldCipher({DEK_VERSION: dek}, DEK_VERSION)

    def enc(columna: str, valor: str) -> bytes:
        return cipher.encrypt(valor.strip(), FieldContext("clinica", columna, cid, cid))

    await db.execute(
        text(
            "INSERT INTO clinica (id, nombre, tipo_persona, nombre_legal, rfc, "
            "representante_nombre, representante_curp, zona_horaria, plan, vigencia_hasta, "
            "dek_wrapped, dek_version) VALUES (:id, :n, :tp, :nl, :rfc, :rn, :rc, :z, :p, :v, "
            ":dw, :dv)"
        ),
        {
            "id": cid,
            "n": body.nombre.strip(),
            "tp": body.tipo_persona,
            "nl": body.nombre_legal.strip(),
            "rfc": enc("rfc", body.rfc.upper()),
            "rn": enc("representante_nombre", body.representante_nombre),
            "rc": enc("representante_curp", body.representante_curp.upper()),
            "z": body.zona_horaria,
            "p": body.plan,
            "v": body.vigencia_hasta,
            "dw": wrap_dek(provider, dek, f"clinica|{cid}|v{DEK_VERSION}"),
            "dv": DEK_VERSION,
        },
    )
    iid = uuid4()
    token = new_token()
    expira = (
        await db.execute(
            text(
                "INSERT INTO invitacion (id, email, email_idx, clinica_id, rol, token_hash, "
                "expira_en, creada_por) VALUES (:i, :e, :x, :c, 'admin', :h, "
                "now() + make_interval(hours => :hr), :cp) RETURNING expira_en"
            ),
            {
                "i": iid,
                "e": _cifrar_email(platform, body.email_admin, iid),
                "x": platform.email_idx(body.email_admin),
                "c": cid,
                "h": hash_token(token),
                "hr": settings.invitacion_horas,
                "cp": op.usuario_id,
            },
        )
    ).scalar_one()
    await audit.registrar(
        db,
        accion="clinica_creada",
        actor_usuario_id=op.usuario_id,
        clinica_id=cid,
        entidad="clinica",
        entidad_id=cid,
        ip=client_ip(request, settings),
        metadata={"plan": body.plan, "invitacion_id": str(iid)},
    )
    await db.commit()
    return ClinicaCreada(clinica_id=cid, invitacion_id=iid, token=token, expira_en=expira)


def _cifrar_email(platform: PlatformCrypto, email: str, invitacion_id: UUID) -> bytes:
    return platform.cipher.encrypt(
        email.strip(), platform.ctx("email", invitacion_id, tabla="invitacion")
    )


@router.get("/clinicas")
async def listar_clinicas(db: OpDb) -> list[ClinicaOut]:
    rows = (
        await db.execute(
            text(
                "SELECT id, nombre, plan, estado, vigencia_hasta, notificaciones_whatsapp, "
                "creado_en FROM clinica ORDER BY creado_en DESC"
            )
        )
    ).all()
    return [ClinicaOut.model_validate(r, from_attributes=True) for r in rows]


@router.patch("/clinicas/{clinica_id}", dependencies=CSRF)
async def actualizar_clinica(
    clinica_id: UUID, body: ClinicaPatch, request: Request, db: OpDb, op: OperadorDep
) -> ClinicaOut:
    cambios = {k: getattr(body, k) for k in body.model_fields_set}
    if not cambios or any(v is None for k, v in cambios.items() if k != "vigencia_hasta"):
        raise HTTPException(422, "Cambios inválidos")
    row = (
        await db.execute(
            text(
                "UPDATE clinica SET "
                "plan = CASE WHEN :s_plan THEN CAST(:plan AS text) ELSE plan END, "
                "estado = CASE WHEN :s_estado THEN CAST(:estado AS text) ELSE estado END, "
                "vigencia_hasta = CASE WHEN :s_vig THEN CAST(:vig AS date) "
                "ELSE vigencia_hasta END, "
                "notificaciones_whatsapp = CASE WHEN :s_wa THEN CAST(:wa AS boolean) "
                "ELSE notificaciones_whatsapp END "
                "WHERE id = :_id RETURNING id, nombre, plan, estado, vigencia_hasta, "
                "notificaciones_whatsapp, creado_en"
            ),
            {
                "s_plan": "plan" in cambios,
                "plan": cambios.get("plan"),
                "s_estado": "estado" in cambios,
                "estado": cambios.get("estado"),
                "s_vig": "vigencia_hasta" in cambios,
                "vig": cambios.get("vigencia_hasta"),
                "s_wa": "notificaciones_whatsapp" in cambios,
                "wa": cambios.get("notificaciones_whatsapp"),
                "_id": clinica_id,
            },
        )
    ).first()
    if row is None:
        raise HTTPException(404, "No encontrado")
    if cambios.get("estado") == "suspendida":  # corta el acceso del personal en el acto
        await db.execute(text("DELETE FROM sesion WHERE clinica_id = :c"), {"c": clinica_id})
    await audit.registrar(
        db,
        accion="clinica_actualizada",
        actor_usuario_id=op.usuario_id,
        clinica_id=clinica_id,
        entidad="clinica",
        entidad_id=clinica_id,
        ip=client_ip(request, get_settings()),
        metadata={"campos": sorted(cambios), "estado": cambios.get("estado")},
    )
    await db.commit()
    return ClinicaOut.model_validate(row, from_attributes=True)


@router.get("/clinicas/{clinica_id}/invitaciones")
async def listar_invitaciones(clinica_id: UUID, db: OpDb) -> list[InvitacionOut]:
    rows = (
        await db.execute(
            text(
                "SELECT id, rol, expira_en, usada_en FROM invitacion "
                "WHERE clinica_id = :c ORDER BY expira_en DESC"
            ),
            {"c": clinica_id},
        )
    ).all()
    return [InvitacionOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("/invitaciones/{invitacion_id}/revocar", status_code=204, dependencies=CSRF)
async def revocar_invitacion(
    invitacion_id: UUID, request: Request, db: OpDb, op: OperadorDep
) -> None:
    await _mover_expiracion(db, request, op, invitacion_id, -1, "invitacion_revocada")


@router.post("/invitaciones/{invitacion_id}/extender", status_code=204, dependencies=CSRF)
async def extender_invitacion(
    invitacion_id: UUID, body: ExtenderIn, request: Request, db: OpDb, op: OperadorDep
) -> None:
    await _mover_expiracion(
        db, request, op, invitacion_id, body.horas * 3600, "invitacion_extendida"
    )


async def _mover_expiracion(
    db: AsyncSession,
    request: Request,
    op: SessionData,
    invitacion_id: UUID,
    segundos: int,
    accion: str,
) -> None:
    row = (
        await db.execute(
            text(
                "UPDATE invitacion "
                "SET expira_en = now() + make_interval(secs => CAST(:s AS double precision)) "
                "WHERE id = :i AND usada_en IS NULL RETURNING clinica_id"
            ),
            {"i": invitacion_id, "s": segundos},
        )
    ).first()
    if row is None:
        raise HTTPException(404, "No encontrado")
    await audit.registrar(
        db,
        accion=accion,
        actor_usuario_id=op.usuario_id,
        clinica_id=row.clinica_id,
        entidad="invitacion",
        entidad_id=invitacion_id,
        ip=client_ip(request, get_settings()),
    )
    await db.commit()
