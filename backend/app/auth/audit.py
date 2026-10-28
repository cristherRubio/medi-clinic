"""Servicio de auditoría. `metadata` nunca puede llevar datos personales."""

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_PROHIBIDAS = (
    "email", "correo", "nombre", "name", "telefono", "phone",
    "password", "contrasena", "token", "secret", "totp", "codigo",
)  # fmt: skip


class AuditMetadataError(ValueError):
    pass


def validar_metadata(valor: Any) -> None:
    if isinstance(valor, dict):
        for k, v in valor.items():
            if any(p in str(k).lower() for p in _PROHIBIDAS):
                raise AuditMetadataError(f"Clave de metadata no permitida: {k}")
            validar_metadata(v)
    elif isinstance(valor, list):
        for v in valor:
            validar_metadata(v)


async def registrar(
    session: AsyncSession,
    *,
    accion: str,
    actor_usuario_id: UUID | None = None,
    clinica_id: UUID | None = None,
    entidad: str | None = None,
    entidad_id: UUID | None = None,
    ip: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    meta = metadata or {}
    validar_metadata(meta)
    await session.execute(
        text(
            "INSERT INTO auditoria (clinica_id, actor_usuario_id, accion, entidad, "
            "entidad_id, ip, metadata) VALUES (:cl, :ac, :ax, :en, :ei, "
            "CAST(:ip AS inet), CAST(:m AS jsonb))"
        ),
        {
            "cl": clinica_id,
            "ac": actor_usuario_id,
            "ax": accion,
            "en": entidad,
            "ei": entidad_id,
            "ip": ip,
            "m": json.dumps(meta),
        },
    )
