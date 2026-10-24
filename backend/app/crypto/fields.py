"""Cifrado de campos con AES-256-GCM.

Formato del valor: ``formato(1) | versión_dek(4, big-endian) | nonce(12) | cifrado+tag``.
AAD = encabezado + ``tabla|columna|clinica_id|fila_id``: un valor cifrado solo descifra
en la fila, columna y clínica para la que se creó.
"""

import os
import struct
import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.crypto.errors import DecryptionError, KeyNotFoundError

FORMAT_VERSION = 1
NONCE_SIZE = 12
TAG_SIZE = 16
_HEADER = struct.Struct(">BI")  # formato, versión de DEK


@dataclass(frozen=True)
class FieldContext:
    """Identifica el lugar donde vive el valor. `clinica_id=None` = datos de plataforma."""

    tabla: str
    columna: str
    clinica_id: uuid.UUID | None
    fila_id: uuid.UUID

    def as_bytes(self) -> bytes:
        clinica = str(self.clinica_id) if self.clinica_id is not None else "plataforma"
        return f"{self.tabla}|{self.columna}|{clinica}|{self.fila_id}".encode()


class FieldCipher:
    """Cifra y descifra con las DEK de un dueño (una clínica o la plataforma).

    `deks` mapea versión -> DEK (varias para poder rotar); `active_version` cifra lo nuevo.
    """

    def __init__(self, deks: Mapping[int, bytes], active_version: int) -> None:
        if active_version not in deks:
            raise KeyNotFoundError(f"No existe la DEK versión {active_version}")
        self._deks = dict(deks)
        self._active = active_version

    @property
    def active_version(self) -> int:
        return self._active

    def encrypt(self, plaintext: str, ctx: FieldContext) -> bytes:
        header = _HEADER.pack(FORMAT_VERSION, self._active)
        nonce = os.urandom(NONCE_SIZE)
        sealed = AESGCM(self._deks[self._active]).encrypt(
            nonce, plaintext.encode("utf-8"), header + ctx.as_bytes()
        )
        return header + nonce + sealed

    def decrypt(self, blob: bytes, ctx: FieldContext) -> str:
        return self._decrypt_bytes(blob, ctx).decode("utf-8")

    def key_version_of(self, blob: bytes) -> int:
        """Versión de DEK con la que se cifró el valor (para recifrado por lotes)."""
        if len(blob) < _HEADER.size + NONCE_SIZE + TAG_SIZE:
            raise DecryptionError("Valor cifrado inválido")
        return int(_HEADER.unpack(blob[: _HEADER.size])[1])

    def reencrypt(self, blob: bytes, ctx: FieldContext) -> bytes:
        """Rotación de DEK: devuelve el valor cifrado con la DEK activa."""
        return self.encrypt(self.decrypt(blob, ctx), ctx)

    def _decrypt_bytes(self, blob: bytes, ctx: FieldContext) -> bytes:
        version = self.key_version_of(blob)
        header = blob[: _HEADER.size]
        if _HEADER.unpack(header)[0] != FORMAT_VERSION:
            raise DecryptionError("Formato de valor desconocido")
        dek = self._deks.get(version)
        if dek is None:
            raise KeyNotFoundError(f"No existe la DEK versión {version}")
        nonce = blob[_HEADER.size : _HEADER.size + NONCE_SIZE]
        sealed = blob[_HEADER.size + NONCE_SIZE :]
        try:
            return AESGCM(dek).decrypt(nonce, sealed, header + ctx.as_bytes())
        except InvalidTag:
            raise DecryptionError("No se pudo descifrar el valor") from None
