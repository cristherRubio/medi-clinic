"""Códigos de recuperación de 2FA: 10 de un solo uso, guardados solo como hash."""

import secrets

from app.auth.tokens import hash_token

COUNT = 10


def generate_recovery_codes() -> list[str]:
    """80 bits cada uno, formato `xxxxx-xxxxx-xxxxx-xxxxx`. Se muestran una sola vez."""
    codes = []
    for _ in range(COUNT):
        raw = secrets.token_hex(10)
        codes.append("-".join(raw[i : i + 5] for i in range(0, 20, 5)))
    return codes


def normalize_code(code: str) -> str:
    return code.replace("-", "").replace(" ", "").strip().lower()


def hash_code(code: str) -> bytes:
    return hash_token(normalize_code(code))
