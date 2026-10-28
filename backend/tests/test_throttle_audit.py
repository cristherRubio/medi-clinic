import pytest
from app.auth.audit import AuditMetadataError, validar_metadata
from app.auth.throttle import clave_hash, derive_throttle_key, limite


def test_clave_hash_estable_y_separada_por_tipo() -> None:
    k = derive_throttle_key(b"k" * 32)
    assert len(k) == 32
    assert clave_hash(k, "login_ip", "1.2.3.4") == clave_hash(k, "login_ip", "1.2.3.4")
    assert clave_hash(k, "login_ip", "x") != clave_hash(k, "login_cuenta", "x")
    assert clave_hash(k, "login_ip", "x") != clave_hash(
        derive_throttle_key(b"j" * 32), "login_ip", "x"
    )


def test_limites_por_defecto() -> None:
    assert limite("login_cuenta") == (5, 5)
    assert limite("login_ip") == (20, 20)


def test_metadata_sin_datos_personales() -> None:
    validar_metadata({"motivo": "login_fallido", "intentos": 3, "extra": {"rol": "admin"}})
    for malo in (
        {"email": "x"},
        {"Telefono": "1"},
        {"a": {"nombre_completo": "x"}},
        {"l": [{"token": "t"}]},
    ):
        with pytest.raises(AuditMetadataError):
            validar_metadata(malo)
