"""Proveedores de la KEK (llave maestra). La KEK nunca vive en la base de datos."""

import base64
import binascii
from abc import ABC, abstractmethod
from pathlib import Path

from app.crypto.errors import CryptoError, KeyNotFoundError

KEK_SIZE = 32


class KeyProvider(ABC):
    """Interfaz para obtener la KEK. Futuro: KmsKeyProvider."""

    @property
    @abstractmethod
    def active_version(self) -> int:
        """Versión de KEK con la que se envuelven las DEK nuevas."""

    @abstractmethod
    def get_kek(self, version: int) -> bytes:
        """Devuelve la KEK de esa versión o lanza KeyNotFoundError."""


class FileKeyProvider(KeyProvider):
    """Lee `<directorio>/kek_v<N>` (32 bytes en base64). Soporta varias versiones para rotar."""

    def __init__(self, directory: Path, active_version: int) -> None:
        self._directory = directory
        self._active_version = active_version
        self.get_kek(active_version)  # falla pronto si la KEK activa no existe o es inválida

    @property
    def active_version(self) -> int:
        return self._active_version

    def get_kek(self, version: int) -> bytes:
        path = self._directory / f"kek_v{version}"
        try:
            raw = path.read_text(encoding="ascii").strip()
        except FileNotFoundError:
            raise KeyNotFoundError(f"No existe la KEK versión {version}") from None
        try:
            kek = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError):
            raise CryptoError(f"La KEK versión {version} no es base64 válido") from None
        if len(kek) != KEK_SIZE:
            raise CryptoError(f"La KEK versión {version} debe tener {KEK_SIZE} bytes")
        return kek
