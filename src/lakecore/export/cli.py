"""CLI do export Parquet: `python -m lakecore.export.cli`.

Existe para que o export tenha **um** caminho, chamado tanto pelo Job do cluster
quanto à mão por quem está depurando. Duplicar a lógica num shell script seria
duas implementações para o mesmo trabalho — e a segunda envelhece sem ninguém
notar.

Sai com código != 0 quando não exporta: derivado que não existe mas o processo
diz "ok" é o mesmo padrão de falso positivo que já custou caro neste projeto.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine

from lakecore.export import exportar


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lakecore.export.cli",
        description="Exporta o catálogo para Parquet.",
    )
    parser.add_argument(
        "--destino",
        type=Path,
        default=Path("derived"),
        help="diretório de saída (padrão: ./derived)",
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("LAKECORE_DATABASE_URL"),
        help="URL do catálogo (padrão: LAKECORE_DATABASE_URL)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if not args.url:
        # Recusa explícita em vez de chutar `localhost`: exportar do banco errado
        # produz um derivado com cara de certo e conteúdo de outro lake.
        print(
            "erro: informe --url ou defina LAKECORE_DATABASE_URL. "
            "O export precisa saber qual catálogo servir.",
            file=sys.stderr,
        )
        return 64

    engine = create_engine(args.url, future=True)
    try:
        resultado = exportar(engine, args.destino)
    finally:
        engine.dispose()

    for tabela, linhas in sorted(resultado.linhas_por_tabela.items()):
        print(f"{tabela}: {linhas} linhas")
    print(f"total: {resultado.bytes_totais} bytes em {len(resultado.caminhos)} arquivo(s)")
    for caminho in resultado.caminhos:
        print(f"  {caminho}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
