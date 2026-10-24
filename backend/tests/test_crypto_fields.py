import uuid

import pytest
from app.crypto import (
    DecryptionError,
    FieldCipher,
    FieldContext,
    KeyNotFoundError,
    blind_index,
    generate_dek,
    normalize_email,
)

CLINICA_A = uuid.uuid4()
CLINICA_B = uuid.uuid4()
FILA = uuid.uuid4()


def ctx(clinica: uuid.UUID | None = CLINICA_A, fila: uuid.UUID = FILA) -> FieldContext:
    return FieldContext("paciente", "telefono", clinica, fila)


def make_cipher() -> FieldCipher:
    return FieldCipher({1: generate_dek()}, active_version=1)


def test_roundtrip() -> None:
    cipher = make_cipher()
    blob = cipher.encrypt("valor de prueba", ctx())
    assert b"valor de prueba" not in blob
    assert cipher.decrypt(blob, ctx()) == "valor de prueba"


def test_same_value_encrypts_differently() -> None:
    cipher = make_cipher()
    assert cipher.encrypt("x", ctx()) != cipher.encrypt("x", ctx())


def test_unicode_roundtrip() -> None:
    cipher = make_cipher()
    assert cipher.decrypt(cipher.encrypt("Ñandú á é ü", ctx()), ctx()) == "Ñandú á é ü"


def test_wrong_row_fails() -> None:
    cipher = make_cipher()
    blob = cipher.encrypt("x", ctx())
    with pytest.raises(DecryptionError):
        cipher.decrypt(blob, ctx(fila=uuid.uuid4()))


def test_wrong_clinic_fails() -> None:
    cipher = make_cipher()
    blob = cipher.encrypt("x", ctx(CLINICA_A))
    with pytest.raises(DecryptionError):
        cipher.decrypt(blob, ctx(CLINICA_B))


def test_wrong_column_fails() -> None:
    cipher = make_cipher()
    blob = cipher.encrypt("x", ctx())
    with pytest.raises(DecryptionError):
        cipher.decrypt(blob, FieldContext("paciente", "nombre", CLINICA_A, FILA))


def test_platform_context_differs_from_clinic() -> None:
    cipher = make_cipher()
    blob = cipher.encrypt("x", ctx(None))
    assert cipher.decrypt(blob, ctx(None)) == "x"
    with pytest.raises(DecryptionError):
        cipher.decrypt(blob, ctx(CLINICA_A))


def test_tampered_ciphertext_fails() -> None:
    cipher = make_cipher()
    blob = bytearray(cipher.encrypt("x", ctx()))
    blob[-1] ^= 0x01
    with pytest.raises(DecryptionError):
        cipher.decrypt(bytes(blob), ctx())


def test_tampered_header_fails() -> None:
    cipher = FieldCipher({1: generate_dek(), 2: generate_dek()}, active_version=1)
    blob = bytearray(cipher.encrypt("x", ctx()))
    blob[4] = 2  # cambia la versión de DEK declarada
    with pytest.raises(DecryptionError):
        cipher.decrypt(bytes(blob), ctx())


def test_truncated_value_fails() -> None:
    cipher = make_cipher()
    with pytest.raises(DecryptionError):
        cipher.decrypt(b"\x01\x00", ctx())


def test_other_dek_fails() -> None:
    blob = make_cipher().encrypt("x", ctx())
    with pytest.raises(DecryptionError):
        make_cipher().decrypt(blob, ctx())


def test_unknown_dek_version() -> None:
    blob = FieldCipher({1: generate_dek()}, 1).encrypt("x", ctx())
    other = FieldCipher({2: generate_dek()}, 2)
    with pytest.raises(KeyNotFoundError):
        other.decrypt(blob, ctx())


def test_dek_rotation_reencrypt() -> None:
    old_dek, new_dek = generate_dek(), generate_dek()
    old = FieldCipher({1: old_dek}, 1)
    blob_v1 = old.encrypt("dato", ctx())

    rotated = FieldCipher({1: old_dek, 2: new_dek}, 2)
    assert rotated.decrypt(blob_v1, ctx()) == "dato"  # el dato viejo aún se lee
    assert rotated.key_version_of(blob_v1) == 1

    blob_v2 = rotated.reencrypt(blob_v1, ctx())
    assert rotated.key_version_of(blob_v2) == 2
    # ya no depende de la DEK vieja
    assert FieldCipher({2: new_dek}, 2).decrypt(blob_v2, ctx()) == "dato"


def test_blind_index_is_stable_and_normalized() -> None:
    dek = generate_dek()
    a = blind_index(dek, "email", normalize_email("  Persona@Example.COM "))
    b = blind_index(dek, "email", normalize_email("persona@example.com"))
    assert a == b
    assert len(a) == 32


def test_blind_index_differs_by_value_clinic_and_column() -> None:
    dek_a, dek_b = generate_dek(), generate_dek()
    base = blind_index(dek_a, "telefono", "+520000000000")
    assert base != blind_index(dek_a, "telefono", "+520000000001")
    assert base != blind_index(dek_b, "telefono", "+520000000000")
    assert base != blind_index(dek_a, "email", "+520000000000")


def test_blind_index_does_not_contain_value() -> None:
    value = "+520000000000"
    assert value.encode() not in blind_index(generate_dek(), "telefono", value)
