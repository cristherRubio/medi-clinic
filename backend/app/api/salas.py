"""Salas de la clínica: listar (todos), crear y editar (admin). Se desactivan, no se borran."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import text

from app.api.authz import Actor, requerir
from app.api.deps import SessionDep, client_ip
from app.auth import audit
from app.auth.rbac import Accion
from app.config import get_settings

router = APIRouter(prefix="/api/salas", tags=["salas"])

VerSalas = Annotated[Actor, Depends(requerir(Accion.VER_SALAS))]
GestionarSalas = Annotated[Actor, Depends(requerir(Accion.GESTIONAR_SALAS))]
NombreSala = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class SalaIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=80)


class SalaPatch(BaseModel):
    nombre: NombreSala | None = None
    activa: bool | None = None


class SalaOut(BaseModel):
    id: UUID
    nombre: str
    activa: bool


@router.get("")
async def listar(actor: VerSalas, db: SessionDep) -> list[SalaOut]:
    rows = (
        await db.execute(
            text("SELECT id, nombre, activa FROM sala WHERE clinica_id = :c ORDER BY nombre"),
            {"c": actor.clinica_id},
        )
    ).all()
    salida = [SalaOut.model_validate(r, from_attributes=True) for r in rows]
    await db.commit()
    return salida


@router.post("", status_code=201)
async def crear(body: SalaIn, request: Request, actor: GestionarSalas, db: SessionDep) -> SalaOut:
    row = (
        await db.execute(
            text("INSERT INTO sala (nombre) VALUES (:n) RETURNING id, nombre, activa"),
            {"n": body.nombre.strip()},
        )
    ).one()
    await audit.registrar(
        db,
        accion="sala_creada",
        actor_usuario_id=actor.usuario_id,
        entidad="sala",
        entidad_id=row.id,
        ip=client_ip(request, get_settings()),
    )
    salida = SalaOut.model_validate(row, from_attributes=True)
    await db.commit()
    return salida


@router.patch("/{sala_id}")
async def editar(
    sala_id: UUID, body: SalaPatch, request: Request, actor: GestionarSalas, db: SessionDep
) -> SalaOut:
    cambios = body.model_fields_set
    if not cambios or any(getattr(body, k) is None for k in cambios):
        raise HTTPException(422, "Cambios inválidos")
    row = (
        await db.execute(
            text(
                "UPDATE sala SET "
                "nombre = CASE WHEN :s_n THEN CAST(:n AS text) ELSE nombre END, "
                "activa = CASE WHEN :s_a THEN CAST(:a AS boolean) ELSE activa END "
                "WHERE id = :i AND clinica_id = :c RETURNING id, nombre, activa"
            ),
            {
                "s_n": "nombre" in cambios,
                "n": body.nombre.strip() if body.nombre else None,
                "s_a": "activa" in cambios,
                "a": body.activa,
                "i": sala_id,
                "c": actor.clinica_id,
            },
        )
    ).first()
    if row is None:
        raise HTTPException(404, "No encontrado")
    await audit.registrar(
        db,
        accion="sala_editada",
        actor_usuario_id=actor.usuario_id,
        entidad="sala",
        entidad_id=sala_id,
        ip=client_ip(request, get_settings()),
        metadata={"campos": sorted(cambios)},
    )
    salida = SalaOut.model_validate(row, from_attributes=True)
    await db.commit()
    return salida
