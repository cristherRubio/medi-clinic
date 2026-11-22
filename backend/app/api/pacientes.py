"""Pacientes de la clínica: alta, consulta, búsqueda, edición, autorización, vínculos y borrado.

Visibilidad: admin y asistente ven todos; el médico, solo los vinculados a él
(`paciente_medico`). El borrado es lógico (`eliminado_en`) y solo el admin lo hace y lo ve.
"""

import unicodedata
from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import AfterValidator, BaseModel, Field, StringConstraints
from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.authz import Actor, denegar, requerir
from app.api.deps import PlatformDep, SessionDep, client_ip, get_key_provider
from app.auth import audit, membership
from app.auth.rbac import Accion, Alcance, alcance
from app.config import get_settings
from app.crypto.fields import FieldCipher, FieldContext
from app.crypto.keys import KeyProvider
from app.telefono import normalizar_e164

router = APIRouter(prefix="/api/pacientes", tags=["pacientes"])

VerPacientes = Annotated[Actor, Depends(requerir(Accion.VER_PACIENTES))]
CrearPaciente = Annotated[Actor, Depends(requerir(Accion.CREAR_PACIENTE))]
EditarPaciente = Annotated[Actor, Depends(requerir(Accion.EDITAR_PACIENTE))]
MarcarOptin = Annotated[Actor, Depends(requerir(Accion.MARCAR_OPTIN))]
Reactivar = Annotated[Actor, Depends(requerir(Accion.REACTIVAR_RECORDATORIOS))]
Vincular = Annotated[Actor, Depends(requerir(Accion.VINCULAR_PACIENTES))]
Borrar = Annotated[Actor, Depends(requerir(Accion.BORRAR))]
ProviderDep = Annotated[KeyProvider, Depends(get_key_provider)]

Nombre = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Telefono = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=30),
    AfterValidator(normalizar_e164),
]
ListaMedicos = Annotated[list[UUID], Field(max_length=50)]

NO_ENCONTRADO = "No encontrado"
MEDICO_INVALIDO = "Cada vínculo debe ser un médico activo de la clínica"


class PacienteIn(BaseModel):
    nombre: Nombre
    telefono: Telefono
    telefono_confirmado: Literal[True]  # quien da de alta lo leyó de vuelta al paciente
    medicos: ListaMedicos = Field(default_factory=list)


class PacientePatch(BaseModel):
    nombre: Nombre | None = None
    telefono: Telefono | None = None
    telefono_confirmado: bool = False  # obligatorio si cambia el teléfono
    no_enviar_recordatorios: bool | None = None


class AutorizacionIn(BaseModel):
    autorizado: bool


class MedicosIn(BaseModel):
    medicos: Annotated[list[UUID], Field(min_length=1, max_length=50)]


class BuscarIn(BaseModel):
    q: Nombre


class PacienteOut(BaseModel):
    id: UUID
    nombre: str
    telefono: str  # E.164
    no_enviar_recordatorios: bool
    optin_estado: str
    optin_atestado_en: datetime | None
    medicos: list[UUID]
    eliminado_en: datetime | None


class PacienteGuardado(PacienteOut):
    telefono_repetido: bool  # aviso: otro paciente de la clínica tiene ese teléfono


# --- Consultas ---------------------------------------------------------------------------

_SQL_CONSULTAR = text(
    "SELECT p.id, p.nombre, p.telefono, p.no_enviar_recordatorios, p.optin_estado, "
    "p.optin_atestado_en, p.eliminado_en, "
    "coalesce(array_agg(pm.personal_id ORDER BY pm.personal_id) "
    "FILTER (WHERE pm.personal_id IS NOT NULL), '{}') AS medicos "
    "FROM paciente p "
    "LEFT JOIN paciente_medico pm ON pm.clinica_id = p.clinica_id AND pm.paciente_id = p.id "
    "WHERE p.clinica_id = :c "
    "AND (CAST(:i AS uuid) IS NULL OR p.id = CAST(:i AS uuid)) "
    "AND (:modo = 'todos' OR (:modo = 'eliminados') = (p.eliminado_en IS NOT NULL)) "
    "AND (NOT :propios OR EXISTS (SELECT 1 FROM paciente_medico x "
    "WHERE x.clinica_id = :c AND x.paciente_id = p.id AND x.personal_id = :yo)) "
    "GROUP BY p.id ORDER BY p.creado_en"
)

# Cambiar el teléfono o desmarcar la casilla reinicia el opt-in por completo.
_SQL_REINICIAR_OPTIN = text(
    "UPDATE paciente SET optin_estado = 'sin_solicitar', optin_atestado_por = NULL, "
    "optin_atestado_en = NULL, optin_solicitado_en = NULL, optin_respondido_en = NULL, "
    "optin_plantilla_version = NULL WHERE id = :i AND clinica_id = :c"
)


async def _consultar(
    db: AsyncSession,
    actor: Actor,
    *,
    modo: Literal["activos", "eliminados", "todos"] = "activos",
    paciente_id: UUID | None = None,
) -> Sequence[Row[Any]]:
    return (
        await db.execute(
            _SQL_CONSULTAR,
            {
                "c": actor.clinica_id,
                "i": paciente_id,
                "modo": modo,
                "propios": actor.alcance is Alcance.PROPIOS,
                "yo": actor.personal_id,
            },
        )
    ).all()


def _salida(cipher: FieldCipher, cid: UUID, r: Row[Any]) -> PacienteOut:
    def dec(columna: str) -> str:
        return cipher.decrypt(
            bytes(getattr(r, columna)), FieldContext("paciente", columna, cid, r.id)
        )

    return PacienteOut(
        id=r.id,
        nombre=dec("nombre"),
        telefono=dec("telefono"),
        no_enviar_recordatorios=r.no_enviar_recordatorios,
        optin_estado=r.optin_estado,
        optin_atestado_en=r.optin_atestado_en,
        medicos=list(r.medicos),
        eliminado_en=r.eliminado_en,
    )


async def _uno(db: AsyncSession, provider: KeyProvider, actor: Actor, pid: UUID) -> PacienteOut:
    """Relee un paciente (incluido si está eliminado) tras una mutación, antes del commit."""
    rows = await _consultar(db, actor, modo="todos", paciente_id=pid)
    cipher = await membership.cargar_cipher(db, provider, actor.clinica_id)
    return _salida(cipher, actor.clinica_id, rows[0])


async def _visible(
    db: AsyncSession, actor: Actor, pid: UUID, *, eliminado: bool = False
) -> Row[Any]:
    """Paciente al alcance del actor (bloqueado para la mutación) o 404 uniforme.

    `eliminado=False` exige que esté activo; `True`, que esté eliminado (restaurar).
    """
    row = (
        await db.execute(
            text(
                "SELECT id, telefono_idx, optin_estado, optin_atestado_en FROM paciente p "
                "WHERE p.id = :i AND p.clinica_id = :c "
                "AND (p.eliminado_en IS NOT NULL) = :eliminado "
                "AND (NOT :propios OR EXISTS (SELECT 1 FROM paciente_medico x "
                "WHERE x.clinica_id = :c AND x.paciente_id = p.id AND x.personal_id = :yo)) "
                "FOR UPDATE"
            ),
            {
                "i": pid,
                "c": actor.clinica_id,
                "eliminado": eliminado,
                "propios": actor.alcance is Alcance.PROPIOS,
                "yo": actor.personal_id,
            },
        )
    ).first()
    if row is None:
        raise HTTPException(404, NO_ENCONTRADO)
    return row


async def _validar_medicos(db: AsyncSession, cid: UUID, medicos: list[UUID]) -> list[UUID]:
    unicos = sorted(set(medicos))
    validos = (
        await db.execute(
            text(
                "SELECT count(*) FROM personal WHERE clinica_id = :c AND rol = 'medico' "
                "AND activo AND id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"c": cid, "ids": unicos},
        )
    ).scalar_one()
    if not unicos or validos != len(unicos):
        raise HTTPException(422, MEDICO_INVALIDO)
    return unicos


async def _telefono_repetido(db: AsyncSession, cid: UUID, idx: bytes, pid: UUID) -> bool:
    return bool(
        (
            await db.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM paciente WHERE clinica_id = :c "
                    "AND telefono_idx = :x AND eliminado_en IS NULL AND id <> :i)"
                ),
                {"c": cid, "x": idx, "i": pid},
            )
        ).scalar_one()
    )


async def _auditar(
    db: AsyncSession,
    request: Request,
    actor: Actor,
    accion: str,
    pid: UUID,
    metadata: dict[str, Any] | None = None,
) -> None:
    await audit.registrar(
        db,
        accion=accion,
        actor_usuario_id=actor.usuario_id,
        entidad="paciente",
        entidad_id=pid,
        ip=client_ip(request, get_settings()),
        metadata=metadata,
    )


def _normalizar_nombre(s: str) -> str:
    """Minúsculas y sin acentos, para buscar 'jose' y encontrar 'José'."""
    sin_acentos = "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )
    return sin_acentos.casefold()


# --- Endpoints -----------------------------------------------------------------------------


@router.post("", status_code=201)
async def crear(
    body: PacienteIn,
    request: Request,
    actor: CrearPaciente,
    db: SessionDep,
    provider: ProviderDep,
    platform: PlatformDep,
) -> PacienteGuardado:
    """Admin y asistente vinculan al menos un médico; el médico queda vinculado a sí mismo."""
    cid = actor.clinica_id
    if alcance(actor.rol, Accion.VINCULAR_PACIENTES) is None:
        if set(body.medicos) - {actor.personal_id}:
            await denegar(db, request, actor.usuario_id, Accion.VINCULAR_PACIENTES)
        medicos = [actor.personal_id]
    else:
        medicos = await _validar_medicos(db, cid, body.medicos)

    pid = uuid4()
    idx = platform.telefono_idx(body.telefono)
    repetido = await _telefono_repetido(db, cid, idx, pid)
    cipher = await membership.cargar_cipher(db, provider, cid)
    await db.execute(
        text(
            "INSERT INTO paciente (id, nombre, telefono, telefono_idx, telefono_confirmado_por, "
            "telefono_confirmado_en, creado_por) VALUES (:i, :n, :t, :x, :yo, now(), :yo)"
        ),
        {
            "i": pid,
            "n": cipher.encrypt(body.nombre, FieldContext("paciente", "nombre", cid, pid)),
            "t": cipher.encrypt(body.telefono, FieldContext("paciente", "telefono", cid, pid)),
            "x": idx,
            "yo": actor.personal_id,
        },
    )
    await db.execute(
        text("INSERT INTO paciente_medico (paciente_id, personal_id) VALUES (:p, :m)"),
        [{"p": pid, "m": m} for m in medicos],
    )
    await _auditar(db, request, actor, "paciente_creado", pid, {"medicos": len(medicos)})
    salida = await _uno(db, provider, actor, pid)
    await db.commit()
    return PacienteGuardado(**salida.model_dump(), telefono_repetido=repetido)


@router.get("")
async def listar(
    request: Request,
    actor: VerPacientes,
    db: SessionDep,
    provider: ProviderDep,
    eliminados: bool = False,
) -> list[PacienteOut]:
    """`?eliminados=true` lista solo los borrados (solo admin)."""
    if eliminados and alcance(actor.rol, Accion.BORRAR) is None:
        await denegar(db, request, actor.usuario_id, Accion.BORRAR)
    rows = await _consultar(db, actor, modo="eliminados" if eliminados else "activos")
    cipher = await membership.cargar_cipher(db, provider, actor.clinica_id)
    salida = [_salida(cipher, actor.clinica_id, r) for r in rows]
    await db.commit()
    return salida


@router.post("/buscar")
async def buscar(
    body: BuscarIn, actor: VerPacientes, db: SessionDep, provider: ProviderDep
) -> list[PacienteOut]:
    """Por nombre, en memoria (los nombres están cifrados). POST para no poner el nombre en
    la URL."""
    rows = await _consultar(db, actor)
    cipher = await membership.cargar_cipher(db, provider, actor.clinica_id)
    q = _normalizar_nombre(body.q)
    salida = [
        p
        for p in (_salida(cipher, actor.clinica_id, r) for r in rows)
        if q in _normalizar_nombre(p.nombre)
    ]
    await db.commit()
    return salida


@router.get("/{paciente_id}")
async def ver(
    paciente_id: UUID, actor: VerPacientes, db: SessionDep, provider: ProviderDep
) -> PacienteOut:
    modo: Literal["activos", "todos"] = (
        "todos" if alcance(actor.rol, Accion.BORRAR) is not None else "activos"
    )
    rows = await _consultar(db, actor, modo=modo, paciente_id=paciente_id)
    if not rows:
        raise HTTPException(404, NO_ENCONTRADO)
    cipher = await membership.cargar_cipher(db, provider, actor.clinica_id)
    salida = _salida(cipher, actor.clinica_id, rows[0])
    await db.commit()
    return salida


@router.patch("/{paciente_id}")
async def editar(
    paciente_id: UUID,
    body: PacientePatch,
    request: Request,
    actor: EditarPaciente,
    db: SessionDep,
    provider: ProviderDep,
    platform: PlatformDep,
) -> PacienteGuardado:
    """Cambiar el teléfono exige confirmarlo de nuevo y reinicia el opt-in."""
    cambios = body.model_fields_set - {"telefono_confirmado"}
    if not cambios or any(getattr(body, c) is None for c in cambios):
        raise HTTPException(422, "Cambios inválidos")
    if "telefono" in cambios and not body.telefono_confirmado:
        raise HTTPException(422, "Confirma el teléfono con el paciente")

    cid = actor.clinica_id
    actual = await _visible(db, actor, paciente_id)
    cambia_tel = False
    idx: bytes | None = None
    if body.telefono is not None:
        idx = platform.telefono_idx(body.telefono)
        cambia_tel = idx != bytes(actual.telefono_idx)
    cipher = await membership.cargar_cipher(db, provider, cid)

    def enc(columna: str, valor: str | None) -> bytes | None:
        if valor is None:
            return None
        return cipher.encrypt(valor, FieldContext("paciente", columna, cid, paciente_id))

    await db.execute(
        text(
            "UPDATE paciente SET "
            "nombre = CASE WHEN :s_n THEN CAST(:n AS bytea) ELSE nombre END, "
            "telefono = CASE WHEN :s_t THEN CAST(:t AS bytea) ELSE telefono END, "
            "telefono_idx = CASE WHEN :s_t THEN CAST(:x AS bytea) ELSE telefono_idx END, "
            "telefono_confirmado_por = CASE WHEN :s_t THEN CAST(:yo AS uuid) "
            "ELSE telefono_confirmado_por END, "
            "telefono_confirmado_en = CASE WHEN :s_t THEN now() "
            "ELSE telefono_confirmado_en END, "
            "no_enviar_recordatorios = CASE WHEN :s_r THEN CAST(:r AS boolean) "
            "ELSE no_enviar_recordatorios END "
            "WHERE id = :i AND clinica_id = :c"
        ),
        {
            "s_n": "nombre" in cambios,
            "n": enc("nombre", body.nombre),
            "s_t": cambia_tel,
            "t": enc("telefono", body.telefono) if cambia_tel else None,
            "x": idx if cambia_tel else None,
            "yo": actor.personal_id,
            "s_r": "no_enviar_recordatorios" in cambios,
            "r": body.no_enviar_recordatorios,
            "i": paciente_id,
            "c": cid,
        },
    )
    if cambia_tel:
        await db.execute(_SQL_REINICIAR_OPTIN, {"i": paciente_id, "c": cid})
    repetido = (
        idx is not None and cambia_tel and await _telefono_repetido(db, cid, idx, paciente_id)
    )
    await _auditar(
        db,
        request,
        actor,
        "paciente_editado",
        paciente_id,
        {"campos": sorted(cambios), "optin_reiniciado": cambia_tel},
    )
    salida = await _uno(db, provider, actor, paciente_id)
    await db.commit()
    return PacienteGuardado(**salida.model_dump(), telefono_repetido=repetido)


@router.post("/{paciente_id}/autorizacion")
async def autorizacion(
    paciente_id: UUID,
    body: AutorizacionIn,
    request: Request,
    actor: MarcarOptin,
    db: SessionDep,
    provider: ProviderDep,
) -> PacienteOut:
    """Casilla "El paciente autorizó recibir recordatorios por WhatsApp".

    Marcarla registra quién y cuándo atestó; desmarcarla vuelve a `sin_solicitar`.
    """
    cid = actor.clinica_id
    actual = await _visible(db, actor, paciente_id)
    marcada = actual.optin_atestado_en is not None
    if body.autorizado and not marcada:
        await db.execute(
            text(
                "UPDATE paciente SET optin_atestado_por = :yo, optin_atestado_en = now() "
                "WHERE id = :i AND clinica_id = :c"
            ),
            {"yo": actor.personal_id, "i": paciente_id, "c": cid},
        )
    elif not body.autorizado and (marcada or actual.optin_estado != "sin_solicitar"):
        await db.execute(_SQL_REINICIAR_OPTIN, {"i": paciente_id, "c": cid})
    else:
        salida = await _uno(db, provider, actor, paciente_id)
        await db.commit()  # sin cambios: idempotente, sin auditoría
        return salida
    await _auditar(
        db, request, actor, "paciente_autorizacion", paciente_id, {"autorizado": body.autorizado}
    )
    salida = await _uno(db, provider, actor, paciente_id)
    await db.commit()
    return salida


@router.post("/{paciente_id}/reactivar-recordatorios")
async def reactivar_recordatorios(
    paciente_id: UUID, request: Request, actor: Reactivar, db: SessionDep, provider: ProviderDep
) -> PacienteOut:
    """Tras un rechazo, a petición del paciente: vuelve a `sin_solicitar` para repetir el
    opt-in (hay que marcar de nuevo la casilla).

    Fase 2: aquí también se marcará `reactivada_en` en `baja_whatsapp` para su teléfono.
    """
    actual = await _visible(db, actor, paciente_id)
    if actual.optin_estado != "rechazado":
        raise HTTPException(409, "No hay recordatorios que reactivar")
    await db.execute(_SQL_REINICIAR_OPTIN, {"i": paciente_id, "c": actor.clinica_id})
    await _auditar(db, request, actor, "recordatorios_reactivados", paciente_id)
    salida = await _uno(db, provider, actor, paciente_id)
    await db.commit()
    return salida


@router.put("/{paciente_id}/medicos")
async def vincular(
    paciente_id: UUID,
    body: MedicosIn,
    request: Request,
    actor: Vincular,
    db: SessionDep,
    provider: ProviderDep,
) -> PacienteOut:
    """Reemplaza los médicos vinculados (al menos uno, todos médicos activos)."""
    cid = actor.clinica_id
    await _visible(db, actor, paciente_id)
    medicos = await _validar_medicos(db, cid, body.medicos)
    await db.execute(
        text(
            "DELETE FROM paciente_medico WHERE clinica_id = :c AND paciente_id = :p "
            "AND personal_id <> ALL(CAST(:ids AS uuid[]))"
        ),
        {"c": cid, "p": paciente_id, "ids": medicos},
    )
    await db.execute(
        text(
            "INSERT INTO paciente_medico (paciente_id, personal_id) VALUES (:p, :m) "
            "ON CONFLICT DO NOTHING"
        ),
        [{"p": paciente_id, "m": m} for m in medicos],
    )
    await _auditar(db, request, actor, "paciente_vinculado", paciente_id, {"medicos": len(medicos)})
    salida = await _uno(db, provider, actor, paciente_id)
    await db.commit()
    return salida


@router.delete("/{paciente_id}", status_code=204)
async def eliminar(paciente_id: UUID, request: Request, actor: Borrar, db: SessionDep) -> None:
    """Borrado lógico; los datos se conservan hasta la purga (plazo por definir)."""
    await _visible(db, actor, paciente_id)
    citas_futuras = (
        await db.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM evento_agenda WHERE clinica_id = :c "
                "AND paciente_id = :i AND estado <> 'cancelada' AND upper(rango) > now())"
            ),
            {"c": actor.clinica_id, "i": paciente_id},
        )
    ).scalar_one()
    if citas_futuras:
        raise HTTPException(409, "Tiene citas futuras: cancélalas antes")
    await db.execute(
        text("UPDATE paciente SET eliminado_en = now() WHERE id = :i AND clinica_id = :c"),
        {"i": paciente_id, "c": actor.clinica_id},
    )
    await _auditar(db, request, actor, "paciente_eliminado", paciente_id)
    await db.commit()


@router.post("/{paciente_id}/restaurar")
async def restaurar(
    paciente_id: UUID, request: Request, actor: Borrar, db: SessionDep, provider: ProviderDep
) -> PacienteOut:
    await _visible(db, actor, paciente_id, eliminado=True)
    await db.execute(
        text("UPDATE paciente SET eliminado_en = NULL WHERE id = :i AND clinica_id = :c"),
        {"i": paciente_id, "c": actor.clinica_id},
    )
    await _auditar(db, request, actor, "paciente_restaurado", paciente_id)
    salida = await _uno(db, provider, actor, paciente_id)
    await db.commit()
    return salida
