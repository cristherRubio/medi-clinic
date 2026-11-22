"""Dependencia de autorización: sesión completa + contexto de clínica + rol vigente."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PlatformDep, SessionDep, client_ip, sesion_completa, verificar_csrf
from app.auth import audit, membership
from app.auth.rbac import Accion, Alcance, Rol, alcance
from app.auth.sessions import SessionData
from app.config import get_settings

_METODOS_SEGUROS = {"GET", "HEAD", "OPTIONS"}


@dataclass(frozen=True)
class Actor:
    usuario_id: UUID
    personal_id: UUID
    clinica_id: UUID
    rol: Rol
    alcance: Alcance


async def denegar(
    db: AsyncSession, request: Request, usuario_id: UUID, accion: Accion | str
) -> NoReturn:
    """403 auditado (`acceso_denegado`). Requiere el contexto de clínica fijado.

    Hace commit antes de responder para que el registro sobreviva al error; llámalo antes
    de cualquier escritura del endpoint.
    """
    await audit.registrar(
        db,
        accion="acceso_denegado",
        actor_usuario_id=usuario_id,
        ip=client_ip(request, get_settings()),
        metadata={"accion": str(accion), "metodo": request.method, "ruta": request.url.path},
    )
    await db.commit()
    raise HTTPException(403, "Sin permiso")


def requerir(accion: Accion) -> Callable[..., Awaitable[Actor]]:
    """Uso: `actor: Annotated[Actor, Depends(requerir(Accion.BORRAR))]`.

    Fija `app.clinica_id` en la transacción de la petición (dura hasta el commit:
    tras un commit, el endpoint debe volver a llamar a `membership.fijar_contexto`).
    CSRF se exige en métodos que modifican.
    """

    async def dependencia(
        request: Request,
        db: SessionDep,
        platform: PlatformDep,
        data: Annotated[SessionData, Depends(sesion_completa)],
    ) -> Actor:
        if data.clinica_id is None or data.personal_id is None:
            raise HTTPException(404, "No encontrado")  # operador o sin contexto elegido
        if request.method not in _METODOS_SEGUROS:
            await verificar_csrf(request, data, platform)
        await membership.fijar_contexto(db, data.clinica_id)
        row = (
            await db.execute(
                text(
                    "SELECT p.rol, p.activo AS p_activo, c.estado "
                    "FROM personal p JOIN clinica c ON c.id = p.clinica_id "
                    "WHERE p.id = :p AND p.usuario_id = :u"
                ),
                {"p": data.personal_id, "u": data.usuario_id},
            )
        ).first()
        if row is None or not row.p_activo or row.estado == "suspendida":
            raise HTTPException(404, "No encontrado")
        rol = Rol(row.rol)
        permitido = alcance(rol, accion)
        if permitido is None:
            await denegar(db, request, data.usuario_id, accion)
        return Actor(data.usuario_id, data.personal_id, data.clinica_id, rol, permitido)

    return dependencia
