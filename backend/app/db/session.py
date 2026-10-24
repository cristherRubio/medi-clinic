"""Motor async y sesión con contexto de clínica (base de RLS)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings, get_settings


def make_engine(rol: str, settings: Settings | None = None) -> AsyncEngine:
    """Motor para un rol de BD. La API usa `app`; el panel del operador, `operador`."""
    s = settings or get_settings()
    return create_async_engine(s.database_url(rol), pool_pre_ping=True)


@asynccontextmanager
async def clinic_session(engine: AsyncEngine, clinica_id: UUID) -> AsyncIterator[AsyncSession]:
    """Sesión en una transacción con `app.clinica_id` fijado (equivale a SET LOCAL).

    Al terminar hace commit; si hay error, rollback. El contexto desaparece con la transacción.
    """
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.clinica_id', :cid, true)"),
            {"cid": str(clinica_id)},
        )
        yield session
