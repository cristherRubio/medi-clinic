"""Normalización de teléfonos a E.164 (México por defecto), sin dependencias externas.

Acepta, ignorando espacios, guiones, puntos y paréntesis:
- 10 dígitos nacionales → `+52XXXXXXXXXX`.
- `52` + 10 dígitos, o el formato móvil antiguo `521` + 10 dígitos (se quita el `1`).
- `+52…` con las mismas reglas.
- Cualquier otro `+<código de país>…` de 8 a 15 dígitos (p. ej. `+1…`), tal cual.
"""

import re

_SEPARADORES = re.compile(r"[\s\-.()]")
_DIGITOS = re.compile(r"[0-9]+")


class TelefonoInvalido(ValueError):
    pass


def _mexicano(resto: str) -> str:
    """`resto` = lo que sigue al 52."""
    if len(resto) == 11 and resto.startswith("1"):
        resto = resto[1:]
    if len(resto) != 10:
        raise TelefonoInvalido("Teléfono inválido")
    return "+52" + resto


def normalizar_e164(texto: str) -> str:
    s = _SEPARADORES.sub("", texto.strip())
    internacional = s.startswith("+")
    digitos = s[1:] if internacional else s
    if not _DIGITOS.fullmatch(digitos):
        raise TelefonoInvalido("Teléfono inválido")
    if internacional:
        if digitos.startswith("52"):
            return _mexicano(digitos[2:])
        if digitos.startswith("0") or not 8 <= len(digitos) <= 15:
            raise TelefonoInvalido("Teléfono inválido")
        return "+" + digitos
    if len(digitos) == 10:
        return "+52" + digitos
    if digitos.startswith("52") and len(digitos) in (12, 13):
        return _mexicano(digitos[2:])
    raise TelefonoInvalido("Teléfono inválido")
