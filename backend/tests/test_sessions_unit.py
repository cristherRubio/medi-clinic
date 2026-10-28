import os
from uuid import uuid4

from app.api.deps import parse_ip
from app.auth.platform import PlatformCrypto
from app.auth.sessions import cookie_names, csrf_for
from app.config import Settings, get_settings
from app.crypto.envelope import generate_dek
from app.main import create_app
from starlette.testclient import TestClient


def _platform() -> PlatformCrypto:
    return PlatformCrypto({1: generate_dek()}, 1, os.urandom(32))


def test_csrf_estable_y_ligado_al_token() -> None:
    k = os.urandom(32)
    assert csrf_for(k, "a") == csrf_for(k, "a")
    assert csrf_for(k, "a") != csrf_for(k, "b")
    assert csrf_for(k, "a") != csrf_for(os.urandom(32), "a")


def test_parse_ip() -> None:
    assert parse_ip("203.0.113.7") == "203.0.113.7"
    assert parse_ip("203.0.113.7, 10.0.0.1") == "203.0.113.7"
    assert parse_ip("no-es-ip") is None
    assert parse_ip("testclient") is None
    assert parse_ip(None) is None


def test_cookie_names() -> None:
    assert cookie_names(Settings(entorno="local")) == ("sid", "csrf")
    assert cookie_names(Settings(entorno="produccion")) == ("__Host-sid", "__Host-csrf")


def test_email_idx_normaliza() -> None:
    p = _platform()
    assert p.email_idx(" A@B.com ") == p.email_idx("a@b.com")
    assert p.email_idx("a@b.com") != p.email_idx("c@b.com")


def test_cifrado_ligado_a_la_fila() -> None:
    p = _platform()
    a = uuid4()
    blob = p.cipher.encrypt("dato", p.ctx("email", a))
    assert p.cipher.decrypt(blob, p.ctx("email", a)) == "dato"


def test_cabeceras_de_seguridad(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("APP_ENTORNO", "produccion")
    get_settings.cache_clear()
    try:
        r = TestClient(create_app()).get("/health")
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert "strict-transport-security" in r.headers
