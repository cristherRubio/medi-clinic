"""Configuración central. Nombre y dominio viven solo aquí para renombrar sin dolor.

Los secretos se leen desde archivos (directorio `SECRETS_DIR`), nunca del repositorio.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

APP_NAME_DEFAULT = "medi-clinic"  # {{APP_NAME}} provisional
DOMINIO_DEFAULT = "localhost"  # {{DOMINIO}} pendiente


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
        extra="ignore",
        secrets_dir=None,
    )

    app_name: str = APP_NAME_DEFAULT
    dominio: str = DOMINIO_DEFAULT
    entorno: str = "local"
    secrets_dir: Path = Path("secrets")

    def read_secret(self, name: str) -> str:
        """Lee un secreto desde `<secrets_dir>/<name>`. Nunca se registra en logs."""
        return (self.secrets_dir / name).read_text(encoding="utf-8").strip()


@lru_cache
def get_settings() -> Settings:
    return Settings()
