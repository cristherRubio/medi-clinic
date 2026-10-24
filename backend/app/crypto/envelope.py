"""DEK (llave de datos) y su envoltura con la KEK.

Formato de la DEK envuelta: ``formato(1) | versión_kek(4, big-endian) | nonce(12) | cifrado+tag``.
El encabezado y el contexto van como AAD, así que no se pueden alterar ni mover a otra fila.
"""

import os
import struct

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.crypto.errors import DecryptionError
from app.crypto.keys import KeyProvider

FORMAT_VERSION = 1
DEK_SIZE = 32
NONCE_SIZE = 12
_HEADER = struct.Struct(">BI")  # formato, versión de KEK


def generate_dek() -> bytes:
    return os.urandom(DEK_SIZE)


def _aad(header: bytes, context: str) -> bytes:
    return header + b"dek|" + context.encode("utf-8")


def wrap_dek(provider: KeyProvider, dek: bytes, context: str) -> bytes:
    """Envuelve la DEK con la KEK activa. `context` identifica a quién pertenece
    (p. ej. ``clinica|<uuid>|v1`` o ``plataforma|v1``)."""
    version = provider.active_version
    header = _HEADER.pack(FORMAT_VERSION, version)
    nonce = os.urandom(NONCE_SIZE)
    sealed = AESGCM(provider.get_kek(version)).encrypt(nonce, dek, _aad(header, context))
    return header + nonce + sealed


def unwrap_dek(provider: KeyProvider, wrapped: bytes, context: str) -> bytes:
    if len(wrapped) < _HEADER.size + NONCE_SIZE + 16:
        raise DecryptionError("DEK envuelta inválida")
    header = wrapped[: _HEADER.size]
    fmt, kek_version = _HEADER.unpack(header)
    if fmt != FORMAT_VERSION:
        raise DecryptionError("Formato de DEK desconocido")
    nonce = wrapped[_HEADER.size : _HEADER.size + NONCE_SIZE]
    sealed = wrapped[_HEADER.size + NONCE_SIZE :]
    try:
        return AESGCM(provider.get_kek(kek_version)).decrypt(nonce, sealed, _aad(header, context))
    except InvalidTag:
        raise DecryptionError("No se pudo descifrar la DEK") from None


def rewrap_dek(provider: KeyProvider, wrapped: bytes, context: str) -> bytes:
    """Rotación de KEK: reenvuelve la DEK con la KEK activa sin tocar los datos."""
    return wrap_dek(provider, unwrap_dek(provider, wrapped, context), context)
