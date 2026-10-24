"""Cifrado a nivel de campo (ver sección 8.1 del prompt maestro)."""

from app.crypto.blind_index import blind_index, normalize_email
from app.crypto.envelope import generate_dek, rewrap_dek, unwrap_dek, wrap_dek
from app.crypto.errors import CryptoError, DecryptionError, KeyNotFoundError
from app.crypto.fields import FieldCipher, FieldContext
from app.crypto.keys import FileKeyProvider, KeyProvider

__all__ = [
    "CryptoError",
    "DecryptionError",
    "FieldCipher",
    "FieldContext",
    "FileKeyProvider",
    "KeyNotFoundError",
    "KeyProvider",
    "blind_index",
    "generate_dek",
    "normalize_email",
    "rewrap_dek",
    "unwrap_dek",
    "wrap_dek",
]
