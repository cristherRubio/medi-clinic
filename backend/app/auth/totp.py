"""TOTP (RFC 6238): 6 dígitos, paso de 30 s, tolerancia de ±1 paso."""

import hmac
import time

import pyotp

STEP = 30
WINDOW = 1


def new_totp_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, cuenta: str, emisor: str) -> str:
    """URI para el QR de la app autenticadora. Solo se muestra al propio usuario."""
    return pyotp.TOTP(secret).provisioning_uri(name=cuenta, issuer_name=emisor)


def verify_totp(secret: str, code: str, now: float | None = None) -> int | None:
    """Devuelve el paso (contador) que coincidió, o None.

    El paso sirve para impedir reutilizar un código: guardar el último aceptado
    y rechazar pasos menores o iguales.
    """
    ahora = int(time.time() if now is None else now)
    code = code.strip().replace(" ", "")
    if not (code.isdigit() and len(code) == 6):
        return None
    totp = pyotp.TOTP(secret, interval=STEP)
    base = ahora // STEP
    for offset in range(-WINDOW, WINDOW + 1):
        if hmac.compare_digest(totp.at(ahora, counter_offset=offset), code):
            return base + offset
    return None
