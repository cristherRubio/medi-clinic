"""DEK de plataforma y llaves derivadas de la KEK (throttle y CSRF)."""

from collections.abc import Mapping
from uuid import UUID

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.throttle import derive_throttle_key
from app.crypto.blind_index import blind_index, normalize_email
from app.crypto.envelope import unwrap_dek
from app.crypto.fields import FieldCipher, FieldContext
from app.crypto.keys import KeyProvider
from app.telefono import normalizar_e164

EMAIL_COLUMN = "email"  # misma clave de índice para usuario e invitacion
TELEFONO_COLUMN = "telefono"  # paciente.telefono_idx y baja_whatsapp (comunes a todas las clínicas)


class PlatformCrypto:
    def __init__(self, deks: Mapping[int, bytes], active_version: int, kek: bytes) -> None:
        self.cipher = FieldCipher(deks, active_version)
        self._index_dek = deks[active_version]
        self.throttle_key = derive_throttle_key(kek)
        self.csrf_key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"csrf").derive(
            kek
        )

    def email_idx(self, email: str) -> bytes:
        return blind_index(self._index_dek, EMAIL_COLUMN, normalize_email(email))

    def telefono_idx(self, telefono: str) -> bytes:
        """Clave de plataforma: el mismo teléfono da la misma huella en todas las clínicas."""
        return blind_index(self._index_dek, TELEFONO_COLUMN, normalizar_e164(telefono))

    @staticmethod
    def ctx(columna: str, usuario_id: UUID, tabla: str = "usuario") -> FieldContext:
        return FieldContext(tabla, columna, None, usuario_id)


async def load_platform_crypto(db: AsyncSession, provider: KeyProvider) -> PlatformCrypto:
    rows = (
        await db.execute(
            text("SELECT version, dek_wrapped, activa FROM llave_plataforma ORDER BY version")
        )
    ).all()
    activas = [r.version for r in rows if r.activa]
    if not activas:
        raise RuntimeError("Falta la llave de plataforma (corre bootstrap_platform)")
    deks = {
        r.version: unwrap_dek(provider, bytes(r.dek_wrapped), f"plataforma|v{r.version}")
        for r in rows
    }
    kek = provider.get_kek(provider.active_version)
    return PlatformCrypto(deks, max(activas), kek)
