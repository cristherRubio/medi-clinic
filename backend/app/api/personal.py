"""Personal de la clínica: listar, invitar, editar, desactivar y reactivar."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.authz import Actor, requerir
from app.api.deps import PlatformDep, SessionDep, client_ip, get_key_provider
from app.auth import audit, membership
from app.auth.rbac import Accion, Alcance, alcance
from app.auth.tokens import hash_token, new_token
from app.config import get_settings
from app.crypto.fields import FieldContext
from app.crypto.keys import KeyProvider

router = APIRouter(prefix="/api/personal", tags=["personal"])

Nombre = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
VerPersonal = Annotated[Actor, Depends(requerir(Accion.VER_PERSONAL))]
AgregarMedicos = Annotated[Actor, Depends(requerir(Accion.AGREGAR_MEDICOS))]
Borrar = Annotated[Actor, Depends(requerir(Accion.BORRAR))]
ProviderDep = Annotated[KeyProvider, Depends(get_key_provider)]

PLAN_LIMITE: dict[str, int | None] = {"p5": 5, "p10": 10, "p20": 20, "p50": 50, "custom": None}
NO_ENCONTRADO = "No encontrado"


class PersonalOut(BaseModel):
    id: UUID
    rol: str
    nombre: str
    contacto_preferido: str | None
    activo: bool


class PersonalPatch(BaseModel):
    nombre: Nombre | None = None
    contacto_preferido: str | None = Field(default=None, max_length=200)


class InvitarIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    rol: Literal["asistente", "medico"]  # el rol admin no se invita (uno por clínica)


class InvitacionCreada(BaseModel):
    invitacion_id: UUID
    token: str  # se muestra una sola vez
    expira_en: datetime
    medicos_usados: int
    limite: int | None
    aviso: bool  # al 80 % del plan o más


class InvitacionPendiente(BaseModel):
    id: UUID
    rol: str
    email: str
    expira_en: datetime


async def _cupo(db: AsyncSession, cid: UUID) -> tuple[int | None, int]:
    """(límite, médicos activos + invitaciones pendientes de médico).

    Bloquea la fila de la clínica para que dos invitaciones simultáneas no pasen el tope.
    """
    plan = (
        await db.execute(text("SELECT plan FROM clinica WHERE id = :c FOR UPDATE"), {"c": cid})
    ).scalar_one()
    usados = (
        await db.execute(
            text(
                "SELECT (SELECT count(*) FROM personal "
                "WHERE clinica_id = :c AND rol = 'medico' AND activo) "
                "+ (SELECT count(*) FROM invitacion WHERE clinica_id = :c AND rol = 'medico' "
                "AND usada_en IS NULL AND expira_en > now())"
            ),
            {"c": cid},
        )
    ).scalar_one()
    return PLAN_LIMITE[plan], int(usados)


async def _objetivo(db: AsyncSession, cid: UUID, pid: UUID):  # type: ignore[no-untyped-def]
    row = (
        await db.execute(
            text("SELECT rol, activo FROM personal WHERE id = :i AND clinica_id = :c"),
            {"i": pid, "c": cid},
        )
    ).first()
    if row is None:
        raise HTTPException(404, NO_ENCONTRADO)
    return row


@router.get("")
async def listar(actor: VerPersonal, db: SessionDep, provider: ProviderDep) -> list[PersonalOut]:
    cipher = await membership.cargar_cipher(db, provider, actor.clinica_id)
    rows = (
        await db.execute(
            text(
                "SELECT id, rol, nombre, contacto_preferido, activo FROM personal "
                "WHERE clinica_id = :c AND (NOT :yo OR id = :p) ORDER BY creado_en"
            ),
            {
                "c": actor.clinica_id,
                "yo": actor.alcance is Alcance.PROPIOS,
                "p": actor.personal_id,
            },
        )
    ).all()
    cid = actor.clinica_id
    salida = [
        PersonalOut(
            id=r.id,
            rol=r.rol,
            nombre=cipher.decrypt(bytes(r.nombre), FieldContext("personal", "nombre", cid, r.id)),
            contacto_preferido=(
                cipher.decrypt(
                    bytes(r.contacto_preferido),
                    FieldContext("personal", "contacto_preferido", cid, r.id),
                )
                if r.contacto_preferido is not None
                else None
            ),
            activo=r.activo,
        )
        for r in rows
    ]
    await db.commit()  # persiste el ultimo_uso de la sesión
    return salida


@router.patch("/{personal_id}")
async def editar(
    personal_id: UUID,
    body: PersonalPatch,
    request: Request,
    actor: VerPersonal,
    db: SessionDep,
    provider: ProviderDep,
) -> PersonalOut:
    """Cada quien edita lo suyo; editar a otros exige EDITAR_PERSONAL (admin)."""
    cambios = body.model_fields_set
    if not cambios or ("nombre" in cambios and body.nombre is None):
        raise HTTPException(422, "Cambios inválidos")
    if personal_id != actor.personal_id and alcance(actor.rol, Accion.EDITAR_PERSONAL) is None:
        raise HTTPException(403, "Sin permiso")
    objetivo = await _objetivo(db, actor.clinica_id, personal_id)
    if "contacto_preferido" in cambios and objetivo.rol != "medico":
        raise HTTPException(422, "El contacto preferido es solo para médicos")

    cipher = await membership.cargar_cipher(db, provider, actor.clinica_id)
    cid = actor.clinica_id

    def enc(columna: str, valor: str | None) -> bytes | None:
        if valor is None or not valor.strip():
            return None
        return cipher.encrypt(valor.strip(), FieldContext("personal", columna, cid, personal_id))

    row = (
        await db.execute(
            text(
                "UPDATE personal SET "
                "nombre = CASE WHEN :s_n THEN CAST(:n AS bytea) ELSE nombre END, "
                "contacto_preferido = CASE WHEN :s_c THEN CAST(:c AS bytea) "
                "ELSE contacto_preferido END "
                "WHERE id = :i AND clinica_id = :cid "
                "RETURNING id, rol, nombre, contacto_preferido, activo"
            ),
            {
                "s_n": "nombre" in cambios,
                "n": enc("nombre", body.nombre),
                "s_c": "contacto_preferido" in cambios,
                "c": enc("contacto_preferido", body.contacto_preferido),
                "i": personal_id,
                "cid": cid,
            },
        )
    ).one()
    await audit.registrar(
        db,
        accion="personal_editado",
        actor_usuario_id=actor.usuario_id,
        entidad="personal",
        entidad_id=personal_id,
        ip=client_ip(request, get_settings()),
        metadata={"campos": sorted(cambios)},
    )
    salida = PersonalOut(
        id=row.id,
        rol=row.rol,
        nombre=cipher.decrypt(bytes(row.nombre), FieldContext("personal", "nombre", cid, row.id)),
        contacto_preferido=(
            cipher.decrypt(
                bytes(row.contacto_preferido),
                FieldContext("personal", "contacto_preferido", cid, row.id),
            )
            if row.contacto_preferido is not None
            else None
        ),
        activo=row.activo,
    )
    await db.commit()
    return salida


@router.post("/{personal_id}/desactivar", status_code=204)
async def desactivar(personal_id: UUID, request: Request, actor: Borrar, db: SessionDep) -> None:
    objetivo = await _objetivo(db, actor.clinica_id, personal_id)
    if personal_id == actor.personal_id or objetivo.rol == "admin":
        raise HTTPException(409, "No se puede desactivar a este usuario")
    await db.execute(
        text("UPDATE personal SET activo = false WHERE id = :i AND clinica_id = :c"),
        {"i": personal_id, "c": actor.clinica_id},
    )
    await db.execute(text("DELETE FROM sesion WHERE personal_id = :i"), {"i": personal_id})
    await audit.registrar(
        db,
        accion="personal_desactivado",
        actor_usuario_id=actor.usuario_id,
        entidad="personal",
        entidad_id=personal_id,
        ip=client_ip(request, get_settings()),
    )
    await db.commit()


@router.post("/{personal_id}/reactivar", status_code=204)
async def reactivar(personal_id: UUID, request: Request, actor: Borrar, db: SessionDep) -> None:
    objetivo = await _objetivo(db, actor.clinica_id, personal_id)
    if objetivo.rol == "admin":
        raise HTTPException(409, "No se puede reactivar a este usuario")
    if objetivo.activo:
        await db.commit()
        return
    if objetivo.rol == "medico":
        limite, usados = await _cupo(db, actor.clinica_id)
        if limite is not None and usados >= limite:
            raise HTTPException(409, "Límite de médicos del plan alcanzado")
    await db.execute(
        text("UPDATE personal SET activo = true WHERE id = :i AND clinica_id = :c"),
        {"i": personal_id, "c": actor.clinica_id},
    )
    await audit.registrar(
        db,
        accion="personal_reactivado",
        actor_usuario_id=actor.usuario_id,
        entidad="personal",
        entidad_id=personal_id,
        ip=client_ip(request, get_settings()),
    )
    await db.commit()


@router.post("/invitaciones", status_code=201)
async def invitar(
    body: InvitarIn, request: Request, actor: AgregarMedicos, db: SessionDep, platform: PlatformDep
) -> InvitacionCreada:
    if body.rol == "asistente" and alcance(actor.rol, Accion.AGREGAR_ASISTENTES) is None:
        raise HTTPException(403, "Sin permiso")
    settings = get_settings()
    cid = actor.clinica_id
    email = body.email.strip()
    idx = platform.email_idx(email)

    limite, usados = await _cupo(db, cid)
    if body.rol == "medico" and limite is not None and usados >= limite:
        raise HTTPException(409, "Límite de médicos del plan alcanzado")
    ya_personal = (
        await db.execute(
            text(
                "SELECT 1 FROM personal p JOIN usuario u ON u.id = p.usuario_id "
                "WHERE p.clinica_id = :c AND u.email_idx = :x"
            ),
            {"c": cid, "x": idx},
        )
    ).first()
    pendiente = (
        await db.execute(
            text(
                "SELECT 1 FROM invitacion WHERE clinica_id = :c AND email_idx = :x "
                "AND usada_en IS NULL AND expira_en > now()"
            ),
            {"c": cid, "x": idx},
        )
    ).first()
    if ya_personal is not None or pendiente is not None:
        raise HTTPException(409, "Ese correo ya pertenece o tiene una invitación pendiente")

    iid, token = uuid4(), new_token()
    expira = (
        await db.execute(
            text(
                "INSERT INTO invitacion (id, email, email_idx, clinica_id, rol, token_hash, "
                "expira_en, creada_por) VALUES (:i, :e, :x, :c, :r, :h, "
                "now() + make_interval(hours => :hr), :cp) RETURNING expira_en"
            ),
            {
                "i": iid,
                "e": platform.cipher.encrypt(email, platform.ctx("email", iid, tabla="invitacion")),
                "x": idx,
                "c": cid,
                "r": body.rol,
                "h": hash_token(token),
                "hr": settings.invitacion_horas,
                "cp": actor.usuario_id,
            },
        )
    ).scalar_one()
    nuevos = usados + (1 if body.rol == "medico" else 0)
    await audit.registrar(
        db,
        accion="invitacion_creada",
        actor_usuario_id=actor.usuario_id,
        entidad="invitacion",
        entidad_id=iid,
        ip=client_ip(request, settings),
        metadata={"rol": body.rol},
    )
    await db.commit()
    return InvitacionCreada(
        invitacion_id=iid,
        token=token,
        expira_en=expira,
        medicos_usados=nuevos,
        limite=limite,
        aviso=limite is not None and nuevos * 5 >= limite * 4,
    )


@router.get("/invitaciones")
async def listar_invitaciones(
    actor: VerPersonal, db: SessionDep, platform: PlatformDep
) -> list[InvitacionPendiente]:
    if actor.alcance is not Alcance.TODOS:
        raise HTTPException(403, "Sin permiso")
    rows = (
        await db.execute(
            text(
                "SELECT id, rol, email, expira_en FROM invitacion "
                "WHERE clinica_id = :c AND usada_en IS NULL AND expira_en > now() "
                "ORDER BY expira_en DESC"
            ),
            {"c": actor.clinica_id},
        )
    ).all()
    salida = [
        InvitacionPendiente(
            id=r.id,
            rol=r.rol,
            email=platform.cipher.decrypt(
                bytes(r.email), platform.ctx("email", r.id, tabla="invitacion")
            ),
            expira_en=r.expira_en,
        )
        for r in rows
    ]
    await db.commit()
    return salida


@router.post("/invitaciones/{invitacion_id}/revocar", status_code=204)
async def revocar_invitacion(
    invitacion_id: UUID, request: Request, actor: AgregarMedicos, db: SessionDep
) -> None:
    row = (
        await db.execute(
            text(
                "SELECT rol FROM invitacion WHERE id = :i AND clinica_id = :c AND usada_en IS NULL"
            ),
            {"i": invitacion_id, "c": actor.clinica_id},
        )
    ).first()
    if row is None:
        raise HTTPException(404, NO_ENCONTRADO)
    if row.rol == "asistente" and alcance(actor.rol, Accion.AGREGAR_ASISTENTES) is None:
        raise HTTPException(403, "Sin permiso")
    await db.execute(
        text(
            "UPDATE invitacion SET expira_en = now() - interval '1 second' "
            "WHERE id = :i AND clinica_id = :c"
        ),
        {"i": invitacion_id, "c": actor.clinica_id},
    )
    await audit.registrar(
        db,
        accion="invitacion_revocada",
        actor_usuario_id=actor.usuario_id,
        entidad="invitacion",
        entidad_id=invitacion_id,
        ip=client_ip(request, get_settings()),
    )
    await db.commit()
