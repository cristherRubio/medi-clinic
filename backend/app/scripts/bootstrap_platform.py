"""Crea la llave de plataforma y el primer operador. Se ejecuta una sola vez."""
# ruff: noqa: T201

import asyncio
import sys
from getpass import getpass
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.auth import audit
from app.auth.passwords import PasswordPolicyError, hash_password
from app.auth.platform import PlatformCrypto
from app.auth.recovery import generate_recovery_codes, hash_code
from app.auth.totp import new_totp_secret, provisioning_uri, verify_totp
from app.config import get_settings
from app.crypto.envelope import generate_dek, wrap_dek
from app.crypto.keys import FileKeyProvider, KeyProvider

DEK_VERSION = 1


class BootstrapError(Exception):
    pass


async def crear_operador(
    engine: AsyncEngine,
    provider: KeyProvider,
    *,
    email: str,
    password_hash: str,
    totp_secret: str,
    paso: int,
) -> list[str]:
    """Crea DEK de plataforma + operador con TOTP activo. Devuelve los códigos de recuperación."""
    dek = generate_dek()
    platform = PlatformCrypto(
        {DEK_VERSION: dek}, DEK_VERSION, provider.get_kek(provider.active_version)
    )
    uid = uuid4()
    codigos = generate_recovery_codes()
    async with AsyncSession(engine) as db, db.begin():
        if (await db.execute(text("SELECT 1 FROM llave_plataforma LIMIT 1"))).first():
            raise BootstrapError("La plataforma ya fue inicializada.")
        await db.execute(
            text("INSERT INTO llave_plataforma (version, dek_wrapped) VALUES (:v, :w)"),
            {"v": DEK_VERSION, "w": wrap_dek(provider, dek, f"plataforma|v{DEK_VERSION}")},
        )
        await db.execute(
            text(
                "INSERT INTO usuario (id, email, email_idx, password_hash, totp_secret, "
                "totp_activo, totp_ultimo_paso, es_operador, activo) "
                "VALUES (:i, :e, :x, :p, :t, true, :s, true, true)"
            ),
            {
                "i": uid,
                "e": platform.cipher.encrypt(email, platform.ctx("email", uid)),
                "x": platform.email_idx(email),
                "p": password_hash,
                "t": platform.cipher.encrypt(totp_secret, platform.ctx("totp_secret", uid)),
                "s": paso,
            },
        )
        for codigo in codigos:
            await db.execute(
                text("INSERT INTO codigo_recuperacion (usuario_id, codigo_hash) VALUES (:u, :h)"),
                {"u": uid, "h": hash_code(codigo)},
            )
        await audit.registrar(
            db,
            accion="bootstrap_operador",
            actor_usuario_id=uid,
            entidad="usuario",
            entidad_id=uid,
        )
    return codigos


def _pedir_password_hash() -> str:
    while True:
        password = getpass("Contraseña (12-128 caracteres): ")
        if password != getpass("Repite la contraseña: "):
            print("No coinciden.")
            continue
        try:
            return hash_password(password)
        except PasswordPolicyError as e:
            print(e)


def _pedir_totp(secreto: str, email: str, app_name: str) -> int:
    print("\nAgrega esta cuenta a tu app de autenticación:")
    print(f"  Secreto: {secreto}")
    print(f"  URI:     {provisioning_uri(secreto, email, app_name)}")
    for _ in range(3):
        paso = verify_totp(secreto, input("Código de 6 dígitos: ").strip())
        if paso is not None:
            return paso
        print("Código incorrecto.")
    raise BootstrapError("No se pudo verificar el TOTP.")


async def _main() -> None:
    settings = get_settings()
    provider = FileKeyProvider(settings.secrets_dir, settings.kek_active_version)
    email = input("Email del operador: ").strip()
    if "@" not in email:
        raise BootstrapError("Email inválido.")
    password_hash = _pedir_password_hash()
    secreto = new_totp_secret()
    paso = _pedir_totp(secreto, email, settings.app_name)
    engine = create_async_engine(settings.database_url("migrador"))
    try:
        codigos = await crear_operador(
            engine,
            provider,
            email=email,
            password_hash=password_hash,
            totp_secret=secreto,
            paso=paso,
        )
    finally:
        await engine.dispose()
    print("\nOperador creado. Códigos de recuperación (se muestran UNA sola vez, guárdalos):")
    for c in codigos:
        print(f"  {c}")


def main() -> None:
    try:
        asyncio.run(_main())
    except BootstrapError as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
