"""Contraseñas con argon2id (los parámetros por defecto de argon2-cffi son argon2id)."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

MIN_LENGTH = 12
MAX_LENGTH = 128

_hasher = PasswordHasher()
_DUMMY_HASH = _hasher.hash("contraseña-ficticia-sin-uso")


class PasswordPolicyError(ValueError):
    pass


def validate_password(password: str) -> None:
    if len(password) < MIN_LENGTH:
        raise PasswordPolicyError(f"La contraseña debe tener al menos {MIN_LENGTH} caracteres")
    if len(password) > MAX_LENGTH:
        raise PasswordPolicyError(f"La contraseña no puede pasar de {MAX_LENGTH} caracteres")


def hash_password(password: str) -> str:
    validate_password(password)
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    if len(password) > MAX_LENGTH:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True si el hash usa parámetros viejos; reemplazarlo tras un login correcto."""
    return _hasher.check_needs_rehash(password_hash)


def verify_dummy(password: str) -> None:
    """Gasta el mismo tiempo que una verificación real (usuario inexistente),
    para que el login no revele qué cuentas existen."""
    verify_password(password, _DUMMY_HASH)
