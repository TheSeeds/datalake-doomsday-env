"""Varredura do `drop/` — a porta de entrada que funciona com o serviço fora do ar.

Em cenário degradado alguém copia arquivos na pasta do host e o dado entra quando
o lake voltar. Diferente do upload HTTP, esta porta **não precisa** de processo
escutando.

Ordem das operações (deliberada, e a mesma do domínio):

    lê  →  ingere (objeto no storage + linha no catálogo)  →  arquiva/move

**Nunca apaga antes de confirmar.** Se o move falhar, o arquivo fica em `drop/`
e a próxima execução reprocessa — inofensivo, porque a ingestão é idempotente
por `sha256`. Apagar antes perderia dado se o catálogo falhasse no meio.

Este script não contém regra de negócio: chama `lakecore.ingest()` como a API.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path

from lakecore.adapters.s3_store import from_env
from lakecore.db.catalog import SqlCatalog
from lakecore.fakes import FixedClock
from lakecore.ingestion import ingest
from lakecore.models import IngestRequest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

log = logging.getLogger("lakecore.drop")

DROP_DIR = Path(os.environ.get("DROP_DIR", "/var/lib/datalake/drop"))
ARQUIVAR = os.environ.get("DROP_ARQUIVAR", "true").lower() == "true"
#: Origem registrada no catálogo quando o arquivo veio do `drop/`. O subdiretório
#: dentro de `drop/` vira origem específica (`drop/pendrive` → `pendrive`).
ORIGEM_PADRAO = os.environ.get("DROP_ORIGEM", "drop")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s %(message)s",
    )

    if not DROP_DIR.is_dir():
        # Diretório ausente não é falha de negócio: é configuração. Devolver
        # erro faz o CronJob acumular `Failed` a cada 5 min por um motivo que
        # não tem nada a ver com o dado. Criar e seguir é o comportamento útil.
        log.warning("diretório de drop não existe, criando: %s", DROP_DIR)
        try:
            DROP_DIR.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.error("não consegui criar %s: %s", DROP_DIR, exc)
            return 2

    arquivos = [p for p in sorted(DROP_DIR.rglob("*")) if p.is_file()]
    if not arquivos:
        log.info("drop vazio: %s (nada a fazer)", DROP_DIR)
        return 0

    log.info("processando %d arquivo(s) em %s", len(arquivos), DROP_DIR)

    engine = create_engine(os.environ["LAKECORE_DATABASE_URL"], future=True)
    catalog = SqlCatalog(sessionmaker(bind=engine, expire_on_commit=False))
    store = from_env(dict(os.environ))
    relogio = FixedClock()

    aceitos = duplicados = falhas = 0

    for arquivo in arquivos:
        # `drop/pendrive/foto.jpg` → origem `pendrive`. Proveniência é o que
        # distingue um lake de um diretório compartilhado.
        relativo = arquivo.relative_to(DROP_DIR)
        origem = relativo.parts[0] if len(relativo.parts) > 1 else ORIGEM_PADRAO

        try:
            resultado = ingest(
                IngestRequest(path=str(arquivo), origem=origem),
                store=store,
                catalog=catalog,
                clock=relogio,
            )
        except Exception:
            # Falha em um arquivo não interrompe o lote: um PDF corrompido não
            # deve impedir a ingestão dos outros 200.
            log.exception("falha ao ingerir %s", arquivo)
            falhas += 1
            continue

        if resultado.duplicate:
            duplicados += 1
            log.info("duplicado: %s → %s", arquivo.name, resultado.record.key)
        else:
            aceitos += 1
            log.info("ingerido: %s → %s", arquivo.name, resultado.record.key)

        _arquivar(arquivo)

    log.info(
        "resumo: total=%d aceitos=%d duplicados=%d falhas=%d",
        len(arquivos),
        aceitos,
        duplicados,
        falhas,
    )
    engine.dispose()
    return 1 if falhas else 0


def _arquivar(arquivo: Path) -> None:
    """Move para `_arquivado/` em vez de apagar.

    Se `ARQUIVAR` for falso, o arquivo fica onde está e a próxima execução o
    encontra como duplicado — que é seguro, mas suja o log.
    """
    if not ARQUIVAR:
        return

    destino = DROP_DIR / "_arquivado" / arquivo.name
    destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(arquivo), str(destino))
        log.info("arquivado: %s", destino.name)
    except OSError:
        # Cópia entre filesystems diferentes pode falhar em `move`. O arquivo
        # fica em `drop/`: reprocessar é seguro (idempotente por hash), perder
        # o original não seria.
        log.warning("não consegui arquivar %s; ele será reprocessado", arquivo)


if __name__ == "__main__":
    sys.exit(main())
