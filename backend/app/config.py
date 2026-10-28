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
    # Duracion de sesiones e invite
    session_idle_hours: int = 8
    session_max_hours: int = 24
    invitacion_horas: int = 72
    # Límite de intentos fallidos: (máximo, ventana en minutos)
    login_cuenta_max: int = 5
    login_cuenta_ventana_min: int = 5
    login_ip_max: int = 20
    login_ip_ventana_min: int = 20
    # vida de la sesión entre contraseña y TOTP
    sesion_pendiente_min: int = 10
    # Cabecera con la IP real (p. ej. "CF-Connecting-IP").
    # Solo si el origen está detrás de Cloudflare.
    ip_header: str | None = None
    # intentos por ip
    activar_ip_max: int = 10
    activar_ip_ventana_min: int = 15
    activar_token_max: int = 5  # intentos de TOTP fallidos por invitación
    activar_token_ventana_min: int = 15

    def read_secret(self, name: str) -> str:
        """Lee un secreto desde `<secrets_dir>/<name>`. Nunca se registra en logs."""
        return (self.secrets_dir / name).read_text(encoding="utf-8").strip()

    @property
    def cookie_secure(self) -> bool:
        return self.entorno != "local"

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
