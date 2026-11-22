"""Normalización de teléfonos a E.164 (datos ficticios)."""

import pytest
from app.auth.platform import PlatformCrypto
from app.telefono import TelefonoInvalido, normalizar_e164


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("5512345678", "+525512345678"),
        ("55 1234 5678", "+525512345678"),
        ("(55) 1234-5678", "+525512345678"),
        ("55.1234.5678", "+525512345678"),
        ("525512345678", "+525512345678"),
        ("5215512345678", "+525512345678"),
        ("+52 55 1234 5678", "+525512345678"),
        ("+52 1 55 1234 5678", "+525512345678"),
        ("  +525512345678  ", "+525512345678"),
        ("+1 (202) 555-0100", "+12025550100"),
        ("+34 600 000 000", "+34600000000"),
    ],
)
def test_validos(entrada: str, esperado: str) -> None:
    assert normalizar_e164(entrada) == esperado
    assert normalizar_e164(esperado) == esperado  # idempotente


@pytest.mark.parametrize(
    "entrada",
    [
        "",
        "123",
        "551234567",  # 9 dígitos
        "55123456789",  # 11 dígitos sin prefijo
        "+52551234567",  # +52 con 9 dígitos
        "+5255123456789",  # +52 con 11 dígitos que no empiezan con 1
        "+0123456789",
        "+1234567",  # muy corto
        "+1234567890123456",  # más de 15 dígitos
        "55-1234-abcd",
        "++525512345678",
        "５５１２３４５６７８",  # dígitos de ancho completo
    ],
)
def test_invalidos(entrada: str) -> None:
    with pytest.raises(TelefonoInvalido):
        normalizar_e164(entrada)


def test_indice_igual_en_cualquier_formato() -> None:
    platform = PlatformCrypto({1: b"\x01" * 32}, 1, b"\x02" * 32)
    assert platform.telefono_idx("55 1234 5678") == platform.telefono_idx("+5215512345678")
    assert platform.telefono_idx("5512345678") != platform.telefono_idx("5512345679")
