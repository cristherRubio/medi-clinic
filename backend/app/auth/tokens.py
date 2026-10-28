"""Tokens de sesión e invitación: aleatorios de 256 bits; en la BD solo va su SHA-256."""

import hashlib
import secrets


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()
