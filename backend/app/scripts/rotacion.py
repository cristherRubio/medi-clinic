"""Rotación de llaves (corre como `migrador`). Ver README, sección "Rotación de llaves".

    python -m app.scripts.rotacion estado [--verificar]
    python -m app.scripts.rotacion kek
    python -m app.scripts.rotacion dek (--clinica UUID | --todas) [--lote 500] [--espera 10]

Solo imprime ids, versiones y conteos (nunca datos). Código de salida: 0 bien; 1 error o,
con `estado --verificar`, si hay rotaciones pendientes (útil para cron y monitoreo).
"""
# ruff: noqa: T201

import argparse
import asyncio
import sys
from uuid import UUID

from app.config import get_settings
from app.crypto.errors import CryptoError
from app.crypto.keys import FileKeyProvider
from app.crypto.rotacion import (
    RotacionError,
    estado,
    rotar_dek_clinica,
    rotar_dek_todas,
    rotar_kek,
)
from app.db.session import make_engine


def _argumentos(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="rotacion", description="Rotación de llaves")
    sub = p.add_subparsers(dest="comando", required=True)
    e = sub.add_parser("estado", help="versiones de KEK y DEK en uso")
    e.add_argument("--verificar", action="store_true", help="sale con 1 si hay algo pendiente")
    sub.add_parser("kek", help="reenvuelve todas las DEK con la KEK activa")
    d = sub.add_parser("dek", help="rota la DEK de una clínica o de todas")
    grupo = d.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--clinica", type=UUID)
    grupo.add_argument("--todas", action="store_true")
    d.add_argument("--lote", type=int, default=500, help="filas por transacción")
    d.add_argument("--espera", type=float, default=10.0, help="segundos de gracia")
    return p.parse_args(argv)


async def _correr(args: argparse.Namespace) -> int:
    settings = get_settings()
    provider = FileKeyProvider(settings.secrets_dir, settings.kek_active_version)
    engine = make_engine("migrador")
    try:
        if args.comando == "estado":
            e = await estado(engine, provider.active_version)
            print(f"KEK activa: v{e.kek_activa}")
            for dek, kek in sorted(e.plataforma.items()):
                print(f"  plataforma  DEK v{dek}  KEK v{kek}")
            for c in e.clinicas:
                keks = ",".join(f"v{k}" for k in sorted(c.kek_versiones))
                marca = "  ROTANDO" if c.en_rotacion else ""
                print(f"  {c.clinica_id}  DEK v{c.dek_version}  KEK {keks}{marca}")
            pendientes = e.pendientes()
            for aviso in pendientes:
                print(f"PENDIENTE: {aviso}")
            if not pendientes:
                print("Todo en orden.")
            return 1 if args.verificar and pendientes else 0
        if args.comando == "kek":
            n = await rotar_kek(engine, provider)
            print(f"DEK reenvueltas con la KEK v{provider.active_version}: {n}")
            return 0
        resultados = (
            await rotar_dek_todas(engine, provider, lote=args.lote, espera=args.espera)
            if args.todas
            else [
                await rotar_dek_clinica(
                    engine, provider, args.clinica, lote=args.lote, espera=args.espera
                )
            ]
        )
        for r in resultados:
            como = "nueva" if r.nueva else "reanudada"
            print(f"  {r.clinica_id}  DEK v{r.dek_version} ({como})  recifrados: {r.recifrados}")
        print(f"Clínicas rotadas: {len(resultados)}")
        return 0
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    try:
        return asyncio.run(_correr(_argumentos(argv)))
    except (RotacionError, CryptoError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
