import base64
import os
from pathlib import Path

import pytest
from app.crypto import (
    CryptoError,
    FileKeyProvider,
    KeyNotFoundError,
    generate_dek,
    rewrap_dek,
    unwrap_dek,
    wrap_dek,
)
from app.crypto.errors import DecryptionError


def write_kek(directory: Path, version: int) -> None:
    (directory / f"kek_v{version}").write_text(base64.b64encode(os.urandom(32)).decode())


def test_file_provider_reads_versions(tmp_path: Path) -> None:
    write_kek(tmp_path, 1)
    write_kek(tmp_path, 2)
    provider = FileKeyProvider(tmp_path, active_version=2)
    assert provider.active_version == 2
    assert len(provider.get_kek(1)) == 32
    assert provider.get_kek(1) != provider.get_kek(2)


def test_missing_active_kek_fails_early(tmp_path: Path) -> None:
    with pytest.raises(KeyNotFoundError):
        FileKeyProvider(tmp_path, active_version=1)


def test_invalid_kek_rejected(tmp_path: Path) -> None:
    (tmp_path / "kek_v1").write_text(base64.b64encode(b"corta").decode())
    with pytest.raises(CryptoError):
        FileKeyProvider(tmp_path, active_version=1)


def test_wrap_unwrap_roundtrip(tmp_path: Path) -> None:
    write_kek(tmp_path, 1)
    provider = FileKeyProvider(tmp_path, active_version=1)
    dek = generate_dek()
    wrapped = wrap_dek(provider, dek, "clinica|demo|v1")
    assert dek not in wrapped
    assert unwrap_dek(provider, wrapped, "clinica|demo|v1") == dek


def test_unwrap_with_other_context_fails(tmp_path: Path) -> None:
    write_kek(tmp_path, 1)
    provider = FileKeyProvider(tmp_path, active_version=1)
    wrapped = wrap_dek(provider, generate_dek(), "clinica|a|v1")
    with pytest.raises(DecryptionError):
        unwrap_dek(provider, wrapped, "clinica|b|v1")


def test_tampered_wrapped_dek_fails(tmp_path: Path) -> None:
    write_kek(tmp_path, 1)
    provider = FileKeyProvider(tmp_path, active_version=1)
    wrapped = bytearray(wrap_dek(provider, generate_dek(), "ctx"))
    wrapped[-1] ^= 0x01
    with pytest.raises(DecryptionError):
        unwrap_dek(provider, bytes(wrapped), "ctx")


def test_kek_rotation_rewrap(tmp_path: Path) -> None:
    write_kek(tmp_path, 1)
    old_provider = FileKeyProvider(tmp_path, active_version=1)
    dek = generate_dek()
    wrapped_v1 = wrap_dek(old_provider, dek, "ctx")

    write_kek(tmp_path, 2)
    new_provider = FileKeyProvider(tmp_path, active_version=2)
    wrapped_v2 = rewrap_dek(new_provider, wrapped_v1, "ctx")

    assert wrapped_v2 != wrapped_v1
    assert unwrap_dek(new_provider, wrapped_v2, "ctx") == dek
    # la DEK sigue siendo la misma: los datos cifrados no se tocan
    assert wrapped_v2[1:5] == (2).to_bytes(4, "big")
