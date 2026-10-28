import base64
import logging
import os
from pathlib import Path
from uuid import uuid4

import pyotp
import pytest
from app.auth.passwords import hash_password
from app.auth.totp import new_totp_secret, verify_totp
from app.crypto.keys import FileKeyProvider
from app.db.session import make_engine
from app.scripts.bootstrap_platform import BootstrapError, crear_operador
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.skipif(
    os.environ.get("APP_TEST_DB") != "1", reason="Requiere BD (solo en CI)"
)


@pytest.mark.asyncio
async def test_bootstrap_crea_operador_sin_filtrar_datos(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "kek_v1").write_text(base64.b64encode(os.urandom(32)).decode())
    provider = FileKeyProvider(tmp_path, 1)
    email = f"{uuid4().hex}@prueba.invalid"
    secreto = new_totp_secret()
    paso = verify_totp(secreto, pyotp.TOTP(secreto).now())
    assert paso is not None
    engine = make_engine("migrador")
    caplog.set_level(logging.DEBUG)
    try:
        phash = hash_password("clave-de-prueba-larga")
        codigos = await crear_operador(
            engine, provider, email=email, password_hash=phash, totp_secret=secreto, paso=paso
        )
        assert len(codigos) == 10
        async with AsyncSession(engine) as db:
            u = (
                await db.execute(
                    text(
                        "SELECT id, email, es_operador, totp_activo FROM usuario WHERE es_operador"
                    )
                )
            ).one()
            assert u.es_operador
            assert u.totp_activo
            assert email.encode() not in bytes(u.email)
            with pytest.raises(BootstrapError):
                await crear_operador(
                    engine,
                    provider,
                    email=email,
                    password_hash=phash,
                    totp_secret=secreto,
                    paso=paso,
                )
        for texto in (email, secreto, *codigos):
            assert texto not in caplog.text
    finally:
        async with AsyncSession(engine) as db:
            await db.execute(text("DELETE FROM usuario WHERE es_operador"))
            await db.execute(text("DELETE FROM llave_plataforma"))
            await db.commit()
        await engine.dispose()
