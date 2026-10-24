"""Configuración central. Nombre y dominio viven solo aquí para renombrar sin dolor.

Los secretos se leen desde archivos (directorio `SECRETS_DIR`), nunca del repositorio.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

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
    kek_active_version: int = 1
    db_host: str = "db"
    db_port: int = 5432
    db_name: str = "medi_clinic"

    def read_secret(self, name: str) -> str:
        """Lee un secreto desde `<secrets_dir>/<name>`. Nunca se registra en logs."""
        return (self.secrets_dir / name).read_text(encoding="utf-8").strip()

    def database_url(self, rol: str) -> URL:
        """URL async de un rol de BD (`migrador`, `app` u `operador`)."""
        return URL.create(
            "postgresql+psycopg",
            username=rol,
            password=self.read_secret(f"db_{rol}_password"),
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
