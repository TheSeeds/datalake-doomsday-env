"""Ponto de entrada de linha de comando do `lakecore`.

Existe para que a ingestão seja exercitável **sem** cluster, sem HTTP e sem
banco — o que é o critério de pronto da Onda 1 e o que permite testar o domínio
em milissegundos.

Nesta onda os adaptadores são os fakes em memória. A Fase 4 troca os fakes por
Garage e PostgreSQL sem tocar neste arquivo: é para isso que as portas existem.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lakecore.fakes import FakeCatalog, FakeObjectStore, FixedClock
from lakecore.ingestion import ingest
from lakecore.models import IngestRequest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lakecore",
        description="Ingestão do datalake-doomsday (adaptadores em memória).",
    )
    parser.add_argument("caminhos", nargs="+", type=Path, help="arquivos a ingerir")
    parser.add_argument("--origem", required=True, help="proveniência do dado")
    parser.add_argument("--tipo", default=None, help="sobrescreve o tipo derivado")
    args = parser.parse_args(argv)

    store = FakeObjectStore()
    catalog = FakeCatalog()
    clock = FixedClock()

    aceitos = duplicados = falhas = 0

    for caminho in args.caminhos:
        try:
            resultado = ingest(
                IngestRequest(path=str(caminho), origem=args.origem, tipo=args.tipo),
                store=store,
                catalog=catalog,
                clock=clock,
            )
        except Exception as exc:  # noqa: BLE001 - CLI reporta e continua no lote
            falhas += 1
            print(f"FALHA    {caminho}: {exc}", file=sys.stderr)
            continue

        if resultado.duplicate:
            duplicados += 1
            print(f"IGUAL    {caminho} → {resultado.record.key}")
        else:
            aceitos += 1
            print(f"ACEITO   {caminho} → {resultado.record.key}")

    print(
        f"\ntotal={len(args.caminhos)} aceitos={aceitos} "
        f"iguais={duplicados} falhas={falhas} objetos={store.escritas}"
    )

    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
