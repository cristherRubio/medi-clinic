"""Correo saliente detrás de una interfaz (`EmailProvider`).

- `SinCorreo` (por defecto, `APP_CORREO_PROVEEDOR=ninguno`): no envía nada. Las invitaciones
  devuelven el token una vez y se entregan a mano; el restablecimiento de contraseña no
  está disponible.
- `ResendProvider` (`APP_CORREO_PROVEEDOR=resend`): API HTTP de Resend; lee el secreto
  `resend_api_key`. Remitente en `APP_CORREO_REMITENTE`.

Los correos son texto plano y cortos: sin datos de pacientes. Los enlaces llevan el token
después de `#` (el navegador no lo envía al servidor: no queda en logs de proxy ni de Caddy).
Nunca se registran destinatarios, enlaces ni cuerpos.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import lru_cache

import httpx2

from app.config import Settings, get_settings

RESEND_URL = "https://api.resend.com/emails"


class CorreoError(RuntimeError):
    """El proveedor no aceptó el correo. El mensaje nunca incluye destinatario ni cuerpo."""


@dataclass(frozen=True)
class Correo:
    para: str
    asunto: str
    texto: str


class EmailProvider(ABC):
    @property
    @abstractmethod
    def activo(self) -> bool:
        """False = no hay proveedor configurado (no se envía nada)."""

    @abstractmethod
    async def enviar(self, correo: Correo) -> None:
        """Envía el correo o lanza `CorreoError`."""


class SinCorreo(EmailProvider):
    @property
    def activo(self) -> bool:
        return False

    async def enviar(self, correo: Correo) -> None:
        raise CorreoError("No hay proveedor de correo configurado")


class ResendProvider(EmailProvider):
    def __init__(
        self, api_key: str, remitente: str, transport: httpx2.AsyncBaseTransport | None = None
    ) -> None:
        self._api_key = api_key
        self._remitente = remitente
        self._transport = transport  # en pruebas, un MockTransport

    @property
    def activo(self) -> bool:
        return True

    async def enviar(self, correo: Correo) -> None:
        try:
            async with httpx2.AsyncClient(
                transport=self._transport, timeout=httpx2.Timeout(10.0)
            ) as cliente:
                r = await cliente.post(
                    RESEND_URL,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={
                        "from": self._remitente,
                        "to": [correo.para],
                        "subject": correo.asunto,
                        "text": correo.texto,
                    },
                )
        except httpx2.HTTPError:
            raise CorreoError("No se pudo conectar con el proveedor de correo") from None
        if r.status_code >= 300:
            raise CorreoError(f"El proveedor de correo respondió {r.status_code}")


def crear_proveedor(settings: Settings) -> EmailProvider:
    if settings.correo_proveedor == "resend":
        return ResendProvider(settings.read_secret("resend_api_key"), settings.correo_remitente)
    return SinCorreo()


@lru_cache
def get_correo() -> EmailProvider:
    return crear_proveedor(get_settings())


# --- Plantillas (texto fijo; solo se interpolan valores sin datos de pacientes) -----------

_ROLES = {"admin": "administrador(a)", "asistente": "asistente", "medico": "médico(a)"}


def enlace(settings: Settings, ruta: str, token: str) -> str:
    return f"{settings.url_publica.rstrip('/')}/{ruta}#t={token}"


def invitacion(
    settings: Settings, para: str, clinica: str, rol: str, token: str, horas: int
) -> Correo:
    return Correo(
        para=para,
        asunto=f"Invitación a {clinica} en {settings.app_name}",
        texto=(
            f"Te invitaron a unirte a {clinica} en {settings.app_name} "
            f"como {_ROLES.get(rol, rol)}.\n\n"
            f"Para activar tu cuenta abre este enlace (vence en {horas} horas):\n"
            f"{enlace(settings, 'activar', token)}\n\n"
            "Si no esperabas esta invitación, ignora este correo."
        ),
    )


def restablecimiento(settings: Settings, para: str, token: str, minutos: int) -> Correo:
    return Correo(
        para=para,
        asunto=f"Restablecer tu contraseña de {settings.app_name}",
        texto=(
            f"Recibimos una solicitud para restablecer tu contraseña de {settings.app_name}.\n\n"
            f"Para elegir una nueva abre este enlace (vence en {minutos} minutos):\n"
            f"{enlace(settings, 'restablecer', token)}\n\n"
            "Si no la pediste, ignora este correo: tu contraseña no cambia."
        ),
    )
