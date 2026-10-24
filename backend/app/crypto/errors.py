class CryptoError(Exception):
    """Error base del módulo. Los mensajes nunca incluyen datos ni claves."""


class DecryptionError(CryptoError):
    """No se pudo descifrar: dato alterado, contexto (AAD) distinto o clave incorrecta."""


class KeyNotFoundError(CryptoError):
    """No existe la versión de clave solicitada."""
