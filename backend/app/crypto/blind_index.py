"""Índice ciego: huella HMAC-SHA256 para búsquedas exactas sin descifrar.

La clave se deriva de la DEK con HKDF (una por columna), así que es distinta por clínica.
Si se rota la DEK, los índices deben recalcularse junto con el recifrado.
La normalización de teléfonos (E.164) llega en la Fase 2; aquí el valor ya viene normalizado.
"""

import hashlib
import hmac

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _index_key(dek: bytes, columna: str) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"blind-index|" + columna.encode("utf-8"),
    ).derive(dek)


def blind_index(dek: bytes, columna: str, normalized_value: str) -> bytes:
    key = _index_key(dek, columna)
    return hmac.new(key, normalized_value.encode("utf-8"), hashlib.sha256).digest()
