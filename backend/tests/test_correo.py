"""Proveedores y plantillas de correo (sin red ni BD)."""

import json

import httpx2
import pytest
from app.auth.throttle import limite
from app.config import Settings
from app.correo import (
    RESEND_URL,
    Correo,
    CorreoError,
    ResendProvider,
    SinCorreo,
    crear_proveedor,
    invitacion,
    restablecimiento,
)

TOKEN = "TokenSecreto_abc-123"
SETTINGS = Settings(url_publica="https://app.ejemplo.invalid/", app_name="medi-clinic")


def test_plantilla_invitacion() -> None:
    c = invitacion(SETTINGS, "persona@ejemplo.invalid", "Clínica Sol", "medico", TOKEN, 72)
    assert c.para == "persona@ejemplo.invalid"
    assert c.asunto == "Invitación a Clínica Sol en medi-clinic"
    assert "como médico(a)" in c.texto
    assert "vence en 72 horas" in c.texto
    # El token aparece una sola vez y solo después de `#` (no viaja al servidor).
    assert "https://app.ejemplo.invalid/activar#t=" + TOKEN in c.texto
    assert c.texto.count(TOKEN) == 1
    assert TOKEN not in c.asunto
    assert "persona@ejemplo.invalid" not in c.texto


def test_plantilla_restablecimiento() -> None:
    c = restablecimiento(SETTINGS, "persona@ejemplo.invalid", TOKEN, 60)
    assert "https://app.ejemplo.invalid/restablecer#t=" + TOKEN in c.texto
    assert c.texto.count(TOKEN) == 1
    assert "vence en 60 minutos" in c.texto
    assert "persona@ejemplo.invalid" not in c.texto + c.asunto


def test_proveedor_por_configuracion() -> None:
    assert isinstance(crear_proveedor(Settings(correo_proveedor="ninguno")), SinCorreo)
    assert not SinCorreo().activo


@pytest.mark.asyncio
async def test_resend_envia() -> None:
    peticiones: list[httpx2.Request] = []

    def responder(req: httpx2.Request) -> httpx2.Response:
        peticiones.append(req)
        return httpx2.Response(200, json={"id": "x"})

    p = ResendProvider("re_clave", "App <app@ejemplo.invalid>", httpx2.MockTransport(responder))
    await p.enviar(Correo("persona@ejemplo.invalid", "Asunto", "Texto"))
    (req,) = peticiones
    assert str(req.url) == RESEND_URL
    assert req.headers["Authorization"] == "Bearer re_clave"
    assert json.loads(req.content) == {
        "from": "App <app@ejemplo.invalid>",
        "to": ["persona@ejemplo.invalid"],
        "subject": "Asunto",
        "text": "Texto",
    }


@pytest.mark.asyncio
async def test_resend_errores_sin_datos() -> None:
    rechaza = ResendProvider(
        "re_clave",
        "app@ejemplo.invalid",
        httpx2.MockTransport(lambda r: httpx2.Response(422, json={"to": "persona@..."})),
    )
    with pytest.raises(CorreoError) as e:
        await rechaza.enviar(Correo("persona@ejemplo.invalid", "A", "T"))
    assert str(e.value) == "El proveedor de correo respondió 422"

    def caida(_: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("sin red")

    with pytest.raises(CorreoError, match="No se pudo conectar"):
        await ResendProvider("k", "r", httpx2.MockTransport(caida)).enviar(
            Correo("persona@ejemplo.invalid", "A", "T")
        )


def test_limites_de_restablecimiento() -> None:
    assert limite("olvide_ip") == (5, 15)
    assert limite("olvide_cuenta") == (3, 60)
    assert limite("restablecer_token") == (5, 15)
    assert limite("restablecer_ip") == (10, 15)
