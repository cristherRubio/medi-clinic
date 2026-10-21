from pathlib import Path

import pytest
from app.config import APP_NAME_DEFAULT, DOMINIO_DEFAULT, Settings


def test_defaults() -> None:
    s = Settings()
    assert s.app_name == APP_NAME_DEFAULT
    assert s.dominio == DOMINIO_DEFAULT


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_APP_NAME", "otro-nombre")
    assert Settings().app_name == "otro-nombre"


def test_read_secret(tmp_path: Path) -> None:
    (tmp_path / "demo").write_text("valor-de-prueba\n", encoding="utf-8")
    assert Settings(secrets_dir=tmp_path).read_secret("demo") == "valor-de-prueba"
