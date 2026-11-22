"""Configuración de la clínica: la lee todo el personal; la edita solo el admin.

Solo las columnas que `app` puede actualizar. Datos legales, plan, estado, vigencia y
WhatsApp los cambia el operador.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import AfterValidator, BaseModel, StringConstraints
from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.authz import Actor, requerir
from app.api.deps import SessionDep, client_ip
from app.auth import audit
from app.auth.rbac import Accion
from app.config import get_settings
from app.horario import Horario, ZonaHoraria, cargar_horario

router = APIRouter(prefix="/api/clinica", tags=["clinica"])

VerClinica = Annotated[Actor, Depends(requerir(Accion.VER_CLINICA))]
Configurar = Annotated[Actor, Depends(requerir(Accion.CONFIGURAR_CLINICA))]


def _https(url: str) -> str:
    if not url.startswith("https://") or len(url) <= len("https://") or " " in url:
        raise ValueError("El enlace debe empezar con https://")
    return url


NombreClinica = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]
UrlMapa = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
    AfterValidator(_https),
]
Texto500 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
Texto1000 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]


class ClinicaOut(BaseModel):
    id: UUID
    nombre: str
    zona_horaria: str
    google_maps_url: str | None
    politica_cancelacion: str | None
    plantilla_recordatorio: str | None
    horario_laboral: Horario  # todos los días vacíos = sin restricción
    notificaciones_whatsapp: bool  # solo lectura (lo cambia el operador)


class ClinicaPatch(BaseModel):
    """`null` borra los campos opcionales (los textos también se borran con "")."""

    nombre: NombreClinica | None = None
    zona_horaria: ZonaHoraria | None = None
    google_maps_url: UrlMapa | None = None
    politica_cancelacion: Texto500 | None = None
    plantilla_recordatorio: Texto1000 | None = None
    horario_laboral: Horario | None = None


_OBLIGATORIOS = {"nombre", "zona_horaria", "horario_laboral"}


async def _leer(db: AsyncSession, cid: UUID) -> Row[Any]:
    return (
        await db.execute(
            text(
                "SELECT id, nombre, zona_horaria, google_maps_url, politica_cancelacion, "
                "plantilla_recordatorio, horario_laboral, notificaciones_whatsapp "
                "FROM clinica WHERE id = :c"
            ),
            {"c": cid},
        )
    ).one()


def _salida(r: Row[Any]) -> ClinicaOut:
    return ClinicaOut(
        id=r.id,
        nombre=r.nombre,
        zona_horaria=r.zona_horaria,
        google_maps_url=r.google_maps_url,
        politica_cancelacion=r.politica_cancelacion,
        plantilla_recordatorio=r.plantilla_recordatorio,
        horario_laboral=cargar_horario(r.horario_laboral),
        notificaciones_whatsapp=r.notificaciones_whatsapp,
    )


@router.get("")
async def ver(actor: VerClinica, db: SessionDep) -> ClinicaOut:
    salida = _salida(await _leer(db, actor.clinica_id))
    await db.commit()
    return salida


@router.patch("")
async def editar(
    body: ClinicaPatch, request: Request, actor: Configurar, db: SessionDep
) -> ClinicaOut:
    cambios = body.model_fields_set
    if not cambios or any(getattr(body, c) is None for c in cambios & _OBLIGATORIOS):
        raise HTTPException(422, "Cambios inválidos")

    def opcional(valor: str | None) -> str | None:
        return valor or None  # "" → NULL

    await db.execute(
        text(
            "UPDATE clinica SET "
            "nombre = CASE WHEN :s_n THEN CAST(:n AS text) ELSE nombre END, "
            "zona_horaria = CASE WHEN :s_z THEN CAST(:z AS text) ELSE zona_horaria END, "
            "google_maps_url = CASE WHEN :s_g THEN CAST(:g AS text) ELSE google_maps_url END, "
            "politica_cancelacion = CASE WHEN :s_p THEN CAST(:p AS text) "
            "ELSE politica_cancelacion END, "
            "plantilla_recordatorio = CASE WHEN :s_r THEN CAST(:r AS text) "
            "ELSE plantilla_recordatorio END, "
            "horario_laboral = CASE WHEN :s_h THEN CAST(:h AS jsonb) ELSE horario_laboral END "
            "WHERE id = :c"
        ),
        {
            "s_n": "nombre" in cambios,
            "n": body.nombre,
            "s_z": "zona_horaria" in cambios,
            "z": body.zona_horaria,
            "s_g": "google_maps_url" in cambios,
            "g": opcional(body.google_maps_url),
            "s_p": "politica_cancelacion" in cambios,
            "p": opcional(body.politica_cancelacion),
            "s_r": "plantilla_recordatorio" in cambios,
            "r": opcional(body.plantilla_recordatorio),
            "s_h": "horario_laboral" in cambios,
            "h": body.horario_laboral.model_dump_json() if body.horario_laboral else None,
            "c": actor.clinica_id,
        },
    )
    await audit.registrar(
        db,
        accion="clinica_configurada",
        actor_usuario_id=actor.usuario_id,
        entidad="clinica",
        entidad_id=actor.clinica_id,
        ip=client_ip(request, get_settings()),
        metadata={"campos": sorted(cambios)},
    )
    salida = _salida(await _leer(db, actor.clinica_id))
    await db.commit()
    return salida
