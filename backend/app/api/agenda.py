"""Agenda: eventos (consulta, procedimiento, otra, bloqueo) siempre en la agenda de un médico.

- Las citas nunca se borran: se cancelan (liberan el espacio).
- Fechas sin zona explícita se interpretan en la zona de la clínica; se guardan en UTC.
- Sin doble reserva por médico ni por sala: lo garantiza la BD (exclusiones) → 409.
- Con horario laboral configurado, consulta/procedimiento/otra deben caber en él salvo
  `fuera_de_horario: true` (auditado). Los bloqueos no se restringen.
- Admin y asistente ven y gestionan todo; el médico, solo su agenda.
"""

from datetime import datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, StringConstraints
from sqlalchemy import Row, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.authz import Actor, denegar, requerir
from app.api.deps import SessionDep, client_ip, get_key_provider
from app.auth import audit, membership
from app.auth.rbac import Accion, Alcance, alcance
from app.config import get_settings
from app.crypto.fields import FieldCipher, FieldContext
from app.crypto.keys import KeyProvider
from app.horario import a_utc, cargar_horario

router = APIRouter(prefix="/api/agenda", tags=["agenda"])

VerAgenda = Annotated[Actor, Depends(requerir(Accion.VER_PACIENTES))]
GestionarCitas = Annotated[Actor, Depends(requerir(Accion.GESTIONAR_CITAS))]
ProviderDep = Annotated[KeyProvider, Depends(get_key_provider)]

Tipo = Literal["consulta", "procedimiento", "otra", "bloqueo"]
Comentario = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]

CON_PACIENTE = {"consulta", "procedimiento"}
DURACION_MIN = timedelta(minutes=15)
DURACION_MAX = {"bloqueo": timedelta(days=31)}
DURACION_MAX_CITA = timedelta(hours=12)
RANGO_CONSULTA_MAX = timedelta(days=62)
NO_ENCONTRADO = "No encontrado"


class EventoIn(BaseModel):
    tipo: Tipo
    medico_id: UUID
    sala_id: UUID | None = None
    paciente_id: UUID | None = None
    inicio: datetime  # sin zona = hora de la clínica
    fin: datetime
    comentario: Comentario | None = None  # sin datos de salud (aviso en la UI)
    fuera_de_horario: bool = False


class EventoPatch(BaseModel):
    medico_id: UUID | None = None
    sala_id: UUID | None = None  # null quita la sala
    paciente_id: UUID | None = None
    inicio: datetime | None = None
    fin: datetime | None = None
    comentario: Comentario | None = None  # null o "" lo borra
    fuera_de_horario: bool = False


class EventoOut(BaseModel):
    id: UUID
    tipo: str
    medico_id: UUID
    sala_id: UUID | None
    paciente_id: UUID | None
    paciente_nombre: str | None
    inicio: datetime
    fin: datetime
    estado: str
    comentario: str | None
    cancelada_por: str | None
    creado_por: UUID
    actualizado_por: UUID
    creado_en: datetime
    actualizado_en: datetime


class PacienteRef(BaseModel):
    id: UUID
    nombre: str


class HistorialItem(BaseModel):
    accion: str
    fecha: datetime
    personal_id: UUID | None
    quien: str | None
    campos: list[str]
    paciente_anterior: PacienteRef | None
    paciente_nuevo: PacienteRef | None
    fuera_de_horario: bool
    reprogramado: bool  # volvió a pendiente_envio (hay que recordar de nuevo)


# --- Ayudantes ---------------------------------------------------------------------------


class _Clinica:
    def __init__(self, r: Row[Any]) -> None:
        self.zona: str = r.zona_horaria
        self.horario = cargar_horario(r.horario_laboral)


async def _clinica(db: AsyncSession, cid: UUID) -> _Clinica:
    r = (
        await db.execute(
            text("SELECT zona_horaria, horario_laboral FROM clinica WHERE id = :c"), {"c": cid}
        )
    ).one()
    return _Clinica(r)


async def _permiso_tipo(
    db: AsyncSession, request: Request, actor: Actor, tipo: str, medico_id: UUID
) -> None:
    """Bloqueos con BLOQUEAR_AGENDA, lo demás con GESTIONAR_CITAS; `propios` = su agenda."""
    accion = Accion.BLOQUEAR_AGENDA if tipo == "bloqueo" else Accion.GESTIONAR_CITAS
    permitido = alcance(actor.rol, accion)
    if permitido is None or (permitido is Alcance.PROPIOS and medico_id != actor.personal_id):
        await denegar(db, request, actor.usuario_id, accion)


def _validar_rango(tipo: str, inicio: datetime, fin: datetime) -> None:
    duracion = fin - inicio
    if duracion < DURACION_MIN:
        raise HTTPException(422, "El evento debe durar al menos 15 minutos")
    if duracion > DURACION_MAX.get(tipo, DURACION_MAX_CITA):
        raise HTTPException(422, "El evento es demasiado largo")


def _validar_horario(
    clinica: _Clinica, tipo: str, inicio: datetime, fin: datetime, forzar: bool
) -> bool:
    """Devuelve si el evento queda fuera del horario (y se forzó). Sin forzar: 422."""
    if tipo == "bloqueo" or clinica.horario.dentro(inicio, fin, clinica.zona):
        return False
    if not forzar:
        raise HTTPException(422, "Fuera del horario laboral")
    return True


async def _validar_medico(db: AsyncSession, cid: UUID, medico_id: UUID) -> None:
    ok = (
        await db.execute(
            text(
                "SELECT 1 FROM personal WHERE id = :m AND clinica_id = :c "
                "AND rol = 'medico' AND activo"
            ),
            {"m": medico_id, "c": cid},
        )
    ).first()
    if ok is None:
        raise HTTPException(422, "El médico no es un médico activo de la clínica")


async def _validar_sala(db: AsyncSession, cid: UUID, sala_id: UUID | None) -> None:
    if sala_id is None:
        return
    ok = (
        await db.execute(
            text("SELECT 1 FROM sala WHERE id = :s AND clinica_id = :c AND activa"),
            {"s": sala_id, "c": cid},
        )
    ).first()
    if ok is None:
        raise HTTPException(422, "Sala inválida")


async def _validar_paciente(db: AsyncSession, actor: Actor, paciente_id: UUID) -> None:
    """Activo y visible para el actor (un médico solo agenda a sus pacientes)."""
    ok = (
        await db.execute(
            text(
                "SELECT 1 FROM paciente p WHERE p.id = :i AND p.clinica_id = :c "
                "AND p.eliminado_en IS NULL "
                "AND (NOT :propios OR EXISTS (SELECT 1 FROM paciente_medico x "
                "WHERE x.clinica_id = :c AND x.paciente_id = p.id AND x.personal_id = :yo))"
            ),
            {
                "i": paciente_id,
                "c": actor.clinica_id,
                "propios": actor.alcance is Alcance.PROPIOS,
                "yo": actor.personal_id,
            },
        )
    ).first()
    if ok is None:
        raise HTTPException(422, "Paciente inválido")


async def _vincular(db: AsyncSession, paciente_id: UUID, medico_id: UUID) -> bool:
    """Vincula el paciente al médico de la cita si no lo estaba (para que el médico lo vea)."""
    r = await db.execute(
        text(
            "INSERT INTO paciente_medico (paciente_id, personal_id) VALUES (:p, :m) "
            "ON CONFLICT DO NOTHING RETURNING paciente_id"
        ),
        {"p": paciente_id, "m": medico_id},
    )
    return r.first() is not None


def _conflicto(e: IntegrityError) -> HTTPException | None:
    restriccion = getattr(getattr(e.orig, "diag", None), "constraint_name", None)
    if restriccion == "ex_evento_medico":
        return HTTPException(409, "El médico ya tiene un evento en ese horario")
    if restriccion == "ex_evento_sala":
        return HTTPException(409, "La sala ya está ocupada en ese horario")
    return None


async def _guardar(db: AsyncSession, sql: Any, params: dict[str, Any]) -> None:
    """Ejecuta el INSERT/UPDATE del evento traduciendo las exclusiones a 409."""
    try:
        await db.execute(sql, params)
    except IntegrityError as e:
        await db.rollback()
        error = _conflicto(e)
        if error is None:
            raise
        raise error from None


_SQL_EVENTOS = text(
    "SELECT e.id, e.tipo, e.medico_id, e.sala_id, e.paciente_id, p.nombre AS paciente_nombre, "
    "lower(e.rango) AS inicio, upper(e.rango) AS fin, e.estado, e.comentario, "
    "e.cancelada_por, e.creado_por, e.actualizado_por, e.creado_en, e.actualizado_en "
    "FROM evento_agenda e "
    "LEFT JOIN paciente p ON p.clinica_id = e.clinica_id AND p.id = e.paciente_id "
    "WHERE e.clinica_id = :c "
    "AND (CAST(:i AS uuid) IS NULL OR e.id = CAST(:i AS uuid)) "
    "AND (CAST(:d AS timestamptz) IS NULL "
    "OR e.rango && tstzrange(CAST(:d AS timestamptz), CAST(:h AS timestamptz), '[)')) "
    "AND (CAST(:m AS uuid) IS NULL OR e.medico_id = CAST(:m AS uuid)) "
    "AND (CAST(:s AS uuid) IS NULL OR e.sala_id = CAST(:s AS uuid)) "
    "AND (CAST(:p AS uuid) IS NULL OR e.paciente_id = CAST(:p AS uuid)) "
    "AND (:canceladas OR e.estado <> 'cancelada') "
    "AND (NOT :propios OR e.medico_id = :yo) "
    "ORDER BY lower(e.rango), e.id"
)


async def _eventos(
    db: AsyncSession,
    actor: Actor,
    *,
    evento_id: UUID | None = None,
    desde: datetime | None = None,
    hasta: datetime | None = None,
    medico_id: UUID | None = None,
    sala_id: UUID | None = None,
    paciente_id: UUID | None = None,
    canceladas: bool = True,
) -> list[Row[Any]]:
    return list(
        (
            await db.execute(
                _SQL_EVENTOS,
                {
                    "c": actor.clinica_id,
                    "i": evento_id,
                    "d": desde,
                    "h": hasta,
                    "m": medico_id,
                    "s": sala_id,
                    "p": paciente_id,
                    "canceladas": canceladas,
                    "propios": actor.alcance is Alcance.PROPIOS,
                    "yo": actor.personal_id,
                },
            )
        ).all()
    )


def _salida(cipher: FieldCipher, cid: UUID, r: Row[Any]) -> EventoOut:
    return EventoOut(
        id=r.id,
        tipo=r.tipo,
        medico_id=r.medico_id,
        sala_id=r.sala_id,
        paciente_id=r.paciente_id,
        paciente_nombre=(
            cipher.decrypt(
                bytes(r.paciente_nombre), FieldContext("paciente", "nombre", cid, r.paciente_id)
            )
            if r.paciente_nombre is not None
            else None
        ),
        inicio=r.inicio,
        fin=r.fin,
        estado=r.estado,
        comentario=(
            cipher.decrypt(
                bytes(r.comentario), FieldContext("evento_agenda", "comentario", cid, r.id)
            )
            if r.comentario is not None
            else None
        ),
        cancelada_por=r.cancelada_por,
        creado_por=r.creado_por,
        actualizado_por=r.actualizado_por,
        creado_en=r.creado_en,
        actualizado_en=r.actualizado_en,
    )


async def _uno(db: AsyncSession, provider: KeyProvider, actor: Actor, eid: UUID) -> EventoOut:
    rows = await _eventos(db, actor, evento_id=eid)
    cipher = await membership.cargar_cipher(db, provider, actor.clinica_id)
    return _salida(cipher, actor.clinica_id, rows[0])


async def _visible(db: AsyncSession, actor: Actor, eid: UUID) -> Row[Any]:
    """Evento al alcance del actor, bloqueado para la mutación, o 404 uniforme."""
    row = (
        await db.execute(
            text(
                "SELECT id, tipo, medico_id, sala_id, paciente_id, lower(rango) AS inicio, "
                "upper(rango) AS fin, estado FROM evento_agenda "
                "WHERE id = :i AND clinica_id = :c AND (NOT :propios OR medico_id = :yo) "
                "FOR UPDATE"
            ),
            {
                "i": eid,
                "c": actor.clinica_id,
                "propios": actor.alcance is Alcance.PROPIOS,
                "yo": actor.personal_id,
            },
        )
    ).first()
    if row is None:
        raise HTTPException(404, NO_ENCONTRADO)
    return row


async def _auditar(
    db: AsyncSession, request: Request, actor: Actor, accion: str, eid: UUID, meta: dict[str, Any]
) -> None:
    await audit.registrar(
        db,
        accion=accion,
        actor_usuario_id=actor.usuario_id,
        entidad="evento_agenda",
        entidad_id=eid,
        ip=client_ip(request, get_settings()),
        metadata=meta,
    )


def _cifrar_comentario(
    cipher: FieldCipher, cid: UUID, eid: UUID, comentario: str | None
) -> bytes | None:
    if not comentario:
        return None
    return cipher.encrypt(comentario, FieldContext("evento_agenda", "comentario", cid, eid))


# --- Endpoints -----------------------------------------------------------------------------


@router.get("")
async def listar(
    actor: VerAgenda,
    db: SessionDep,
    provider: ProviderDep,
    desde: datetime,
    hasta: datetime,
    medico_id: UUID | None = None,
    sala_id: UUID | None = None,
    paciente_id: UUID | None = None,
    incluir_canceladas: bool = False,
) -> list[EventoOut]:
    """Eventos que se traslapan con [desde, hasta) (máximo 62 días)."""
    clinica = await _clinica(db, actor.clinica_id)
    d, h = a_utc(desde, clinica.zona), a_utc(hasta, clinica.zona)
    if h <= d or h - d > RANGO_CONSULTA_MAX:
        raise HTTPException(422, "Rango de fechas inválido (máximo 62 días)")
    rows = await _eventos(
        db,
        actor,
        desde=d,
        hasta=h,
        medico_id=medico_id,
        sala_id=sala_id,
        paciente_id=paciente_id,
        canceladas=incluir_canceladas,
    )
    cipher = await membership.cargar_cipher(db, provider, actor.clinica_id)
    salida = [_salida(cipher, actor.clinica_id, r) for r in rows]
    await db.commit()
    return salida


@router.post("", status_code=201)
async def crear(
    body: EventoIn, request: Request, actor: GestionarCitas, db: SessionDep, provider: ProviderDep
) -> EventoOut:
    cid = actor.clinica_id
    await _permiso_tipo(db, request, actor, body.tipo, body.medico_id)
    if (body.tipo in CON_PACIENTE) != (body.paciente_id is not None):
        raise HTTPException(422, "Consulta y procedimiento llevan paciente; otra y bloqueo, no")
    clinica = await _clinica(db, cid)
    inicio, fin = a_utc(body.inicio, clinica.zona), a_utc(body.fin, clinica.zona)
    _validar_rango(body.tipo, inicio, fin)
    fuera = _validar_horario(clinica, body.tipo, inicio, fin, body.fuera_de_horario)
    await _validar_medico(db, cid, body.medico_id)
    await _validar_sala(db, cid, body.sala_id)
    vinculado = False
    if body.paciente_id is not None:
        await _validar_paciente(db, actor, body.paciente_id)
        vinculado = await _vincular(db, body.paciente_id, body.medico_id)

    eid = uuid4()
    cipher = await membership.cargar_cipher(db, provider, cid)
    await _guardar(
        db,
        text(
            "INSERT INTO evento_agenda (id, tipo, medico_id, sala_id, paciente_id, rango, estado, "
            "comentario, creado_por, actualizado_por) VALUES (:i, :t, :m, :s, :p, "
            "tstzrange(:ini, :fin, '[)'), :e, :co, :yo, :yo)"
        ),
        {
            "i": eid,
            "t": body.tipo,
            "m": body.medico_id,
            "s": body.sala_id,
            "p": body.paciente_id,
            "ini": inicio,
            "fin": fin,
            "e": "pendiente_envio" if body.tipo in CON_PACIENTE else "confirmada",
            "co": _cifrar_comentario(cipher, cid, eid, body.comentario),
            "yo": actor.personal_id,
        },
    )
    await _auditar(
        db,
        request,
        actor,
        "evento_creado",
        eid,
        {"tipo": body.tipo, "fuera_de_horario": fuera, "vinculo_automatico": vinculado},
    )
    salida = await _uno(db, provider, actor, eid)
    await db.commit()
    return salida


@router.get("/{evento_id}")
async def ver(
    evento_id: UUID, actor: VerAgenda, db: SessionDep, provider: ProviderDep
) -> EventoOut:
    rows = await _eventos(db, actor, evento_id=evento_id)
    if not rows:
        raise HTTPException(404, NO_ENCONTRADO)
    cipher = await membership.cargar_cipher(db, provider, actor.clinica_id)
    salida = _salida(cipher, actor.clinica_id, rows[0])
    await db.commit()
    return salida


@router.patch("/{evento_id}")
async def editar(
    evento_id: UUID,
    body: EventoPatch,
    request: Request,
    actor: GestionarCitas,
    db: SessionDep,
    provider: ProviderDep,
) -> EventoOut:
    """Mover (horario, médico, sala), cambiar de paciente o editar el comentario.

    Si cambia horario, médico o paciente de una cita ya enviada o confirmada, vuelve a
    `pendiente_envio` (hay que recordar de nuevo). El tipo no cambia.
    """
    cid = actor.clinica_id
    cambios = body.model_fields_set - {"fuera_de_horario"}
    no_nulos = {"medico_id", "paciente_id", "inicio", "fin"}
    if not cambios or any(getattr(body, c) is None for c in cambios & no_nulos):
        raise HTTPException(422, "Cambios inválidos")
    actual = await _visible(db, actor, evento_id)
    if actual.estado == "cancelada":
        raise HTTPException(409, "El evento está cancelado")
    await _permiso_tipo(db, request, actor, actual.tipo, actual.medico_id)

    # medico_id y paciente_id no admiten null (validado arriba); sala_id sí.
    medico_id: UUID = body.medico_id or actual.medico_id
    paciente_id: UUID | None = body.paciente_id or actual.paciente_id
    sala_id = body.sala_id if "sala_id" in cambios else actual.sala_id
    clinica = await _clinica(db, cid)
    inicio = a_utc(body.inicio, clinica.zona) if body.inicio is not None else actual.inicio
    fin = a_utc(body.fin, clinica.zona) if body.fin is not None else actual.fin

    cambia_medico = medico_id != actual.medico_id
    cambia_paciente = paciente_id != actual.paciente_id
    cambia_horario = inicio != actual.inicio or fin != actual.fin
    if cambia_paciente and actual.tipo not in CON_PACIENTE:
        raise HTTPException(422, "Otra y bloqueo no llevan paciente")
    if cambia_medico:
        await _permiso_tipo(db, request, actor, actual.tipo, medico_id)
        await _validar_medico(db, cid, medico_id)
    if sala_id != actual.sala_id:
        await _validar_sala(db, cid, sala_id)
    fuera = False
    if cambia_horario:
        _validar_rango(actual.tipo, inicio, fin)
        fuera = _validar_horario(clinica, actual.tipo, inicio, fin, body.fuera_de_horario)
    vinculado = False
    if cambia_paciente and paciente_id is not None:
        await _validar_paciente(db, actor, paciente_id)
    if paciente_id is not None and (cambia_paciente or cambia_medico):
        vinculado = await _vincular(db, paciente_id, medico_id)
    reprogramado = (
        (cambia_horario or cambia_medico or cambia_paciente)
        and actual.estado
        in (
            "enviado",
            "confirmada",
        )
        and actual.tipo in CON_PACIENTE
    )

    cipher = await membership.cargar_cipher(db, provider, cid)
    await _guardar(
        db,
        text(
            "UPDATE evento_agenda SET medico_id = :m, sala_id = :s, paciente_id = :p, "
            "rango = tstzrange(:ini, :fin, '[)'), "
            "comentario = CASE WHEN :s_co THEN CAST(:co AS bytea) ELSE comentario END, "
            "estado = CASE WHEN :reprog THEN 'pendiente_envio' ELSE estado END, "
            "enviado_en = CASE WHEN :reprog THEN NULL ELSE enviado_en END, "
            "confirmado_en = CASE WHEN :reprog THEN NULL ELSE confirmado_en END, "
            "actualizado_por = :yo, actualizado_en = now() "
            "WHERE id = :i AND clinica_id = :c"
        ),
        {
            "m": medico_id,
            "s": sala_id,
            "p": paciente_id,
            "ini": inicio,
            "fin": fin,
            "s_co": "comentario" in cambios,
            "co": _cifrar_comentario(cipher, cid, evento_id, body.comentario),
            "reprog": reprogramado,
            "yo": actor.personal_id,
            "i": evento_id,
            "c": cid,
        },
    )
    meta: dict[str, Any] = {
        "campos": sorted(cambios),
        "fuera_de_horario": fuera,
        "reprogramado": reprogramado,
        "vinculo_automatico": vinculado,
    }
    if cambia_paciente:
        meta["paciente_anterior"] = str(actual.paciente_id)
        meta["paciente_nuevo"] = str(paciente_id)
    await _auditar(db, request, actor, "evento_editado", evento_id, meta)
    salida = await _uno(db, provider, actor, evento_id)
    await db.commit()
    return salida


@router.post("/{evento_id}/cancelar")
async def cancelar(
    evento_id: UUID, request: Request, actor: GestionarCitas, db: SessionDep, provider: ProviderDep
) -> EventoOut:
    actual = await _visible(db, actor, evento_id)
    await _permiso_tipo(db, request, actor, actual.tipo, actual.medico_id)
    if actual.estado == "cancelada":
        raise HTTPException(409, "El evento ya está cancelado")
    await db.execute(
        text(
            "UPDATE evento_agenda SET estado = 'cancelada', cancelada_por = 'personal', "
            "actualizado_por = :yo, actualizado_en = now() WHERE id = :i AND clinica_id = :c"
        ),
        {"yo": actor.personal_id, "i": evento_id, "c": actor.clinica_id},
    )
    await _auditar(db, request, actor, "evento_cancelado", evento_id, {"tipo": actual.tipo})
    salida = await _uno(db, provider, actor, evento_id)
    await db.commit()
    return salida


@router.get("/{evento_id}/historial")
async def historial(
    evento_id: UUID, actor: VerAgenda, db: SessionDep, provider: ProviderDep
) -> list[HistorialItem]:
    """Quién hizo cada cambio y cuándo (desde `auditoria`), para mostrarlo en la UI."""
    cid = actor.clinica_id
    if not await _eventos(db, actor, evento_id=evento_id):
        raise HTTPException(404, NO_ENCONTRADO)
    rows = (
        await db.execute(
            text(
                "SELECT a.accion, a.creado_en, a.metadata, pe.id AS personal_id, "
                "pe.nombre AS personal_nombre FROM auditoria a "
                "LEFT JOIN personal pe ON pe.clinica_id = a.clinica_id "
                "AND pe.usuario_id = a.actor_usuario_id "
                "WHERE a.clinica_id = :c AND a.entidad = 'evento_agenda' AND a.entidad_id = :i "
                "ORDER BY a.creado_en, a.id"
            ),
            {"c": cid, "i": evento_id},
        )
    ).all()
    cipher = await membership.cargar_cipher(db, provider, cid)

    ids: set[UUID] = set()
    for r in rows:
        meta = r.metadata or {}
        for clave in ("paciente_anterior", "paciente_nuevo"):
            if meta.get(clave) and meta[clave] != "None":
                ids.add(UUID(meta[clave]))
    nombres: dict[UUID, str] = {}
    if ids:
        pacientes = (
            await db.execute(
                text(
                    "SELECT id, nombre FROM paciente "
                    "WHERE clinica_id = :c AND id = ANY(CAST(:ids AS uuid[]))"
                ),
                {"c": cid, "ids": sorted(ids)},
            )
        ).all()
        nombres = {
            p.id: cipher.decrypt(bytes(p.nombre), FieldContext("paciente", "nombre", cid, p.id))
            for p in pacientes
        }

    def ref(valor: str | None) -> PacienteRef | None:
        if not valor or valor == "None":
            return None
        pid = UUID(valor)
        return PacienteRef(id=pid, nombre=nombres[pid]) if pid in nombres else None

    salida = []
    for r in rows:
        meta = r.metadata or {}
        salida.append(
            HistorialItem(
                accion=r.accion,
                fecha=r.creado_en,
                personal_id=r.personal_id,
                quien=(
                    cipher.decrypt(
                        bytes(r.personal_nombre),
                        FieldContext("personal", "nombre", cid, r.personal_id),
                    )
                    if r.personal_nombre is not None
                    else None
                ),
                campos=list(meta.get("campos", [])),
                paciente_anterior=ref(meta.get("paciente_anterior")),
                paciente_nuevo=ref(meta.get("paciente_nuevo")),
                fuera_de_horario=bool(meta.get("fuera_de_horario", False)),
                reprogramado=bool(meta.get("reprogramado", False)),
            )
        )
    await db.commit()
    return salida
