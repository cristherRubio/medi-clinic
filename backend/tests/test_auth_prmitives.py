import pyotp
import pytest
from app.auth.passwords import (
    PasswordPolicyError,
    hash_password,
    needs_rehash,
    verify_dummy,
    verify_password,
)
from app.auth.recovery import COUNT, generate_recovery_codes, hash_code
from app.auth.tokens import hash_token, new_token
from app.auth.totp import new_totp_secret, verify_totp

CLAVE = "una-clave-larga-de-prueba"


def test_password_ida_y_vuelta() -> None:
    h = hash_password(CLAVE)
    assert h.startswith("$argon2id$")
    assert verify_password(CLAVE, h)
    assert not verify_password("otra-clave-distinta", h)
    assert not needs_rehash(h)


def test_password_politica() -> None:
    with pytest.raises(PasswordPolicyError):
        hash_password("corta")
    with pytest.raises(PasswordPolicyError):
        hash_password("x" * 129)


def test_password_hash_invalido_no_revienta() -> None:
    assert not verify_password(CLAVE, "no-es-un-hash")
    assert not verify_password("x" * 500, hash_password(CLAVE))
    verify_dummy(CLAVE)


def test_totp_acepta_ventana_y_rechaza_fuera() -> None:
    secret = new_totp_secret()
    t = 1_800_000_000
    totp = pyotp.TOTP(secret)
    assert verify_totp(secret, totp.at(t), now=t) == t // 30
    assert verify_totp(secret, totp.at(t - 30), now=t) == t // 30 - 1
    assert verify_totp(secret, totp.at(t - 90), now=t) is None


def test_totp_formato_invalido() -> None:
    secret = new_totp_secret()
    for malo in ("", "abc123", "12345", "1234567"):
        assert verify_totp(secret, malo) is None


def test_tokens() -> None:
    a, b = new_token(), new_token()
    assert a != b
    assert len(a) >= 43
    assert hash_token(a) == hash_token(a)
    assert hash_token(a) != hash_token(b)
    assert len(hash_token(a)) == 32


def test_codigos_de_recuperacion() -> None:
    codes = generate_recovery_codes()
    assert len(codes) == COUNT
    assert len(set(codes)) == COUNT
    assert hash_code(codes[0]) == hash_code(codes[0].upper().replace("-", " "))
    assert hash_code(codes[0]) != hash_code(codes[1])
