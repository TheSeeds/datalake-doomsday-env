"""Integração: `ingest()` do domínio gravando em PostgreSQL real.

Este é o teste que liga o domínio puro (Onda 1) ao catálogo persistente (Onda 2).
Sem ele, `lakecore.ingest()` e `SqlCatalog` só são provados em separado — e a
única coisa que importa é que funcionem **juntos**.

O critério da Onda 4 já é exercitado aqui na parte que não depende de storage:
ingerir o mesmo arquivo duas vezes grava **uma** linha.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from lakecore.db.catalog import SqlCatalog
from lakecore.fakes import FakeObjectStore, FixedClock
from lakecore.ingestion import ingest
from lakecore.models import IngestRequest


@pytest.fixture
def catalogo(session_factory: sessionmaker) -> SqlCatalog:
    return SqlCatalog(session_factory)


def test_ingerir_grava_no_postgres(
    tmp_path: Path,
    catalogo: SqlCatalog,
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arquivo = tmp_path / "nota.txt"
    arquivo.write_text("conteudo do doomsday\n")

    resultado = ingest(
        IngestRequest(path=str(arquivo), origem="pendrive"),
        store=FakeObjectStore(),
        catalog=catalogo,
        clock=FixedClock(),
    )

    with engine.connect() as conn:
        linha = conn.execute(
            text("select sha256, origem, tipo, size_bytes from objects")
        ).one()

    assert resultado.duplicate is False
    assert linha.sha256 == resultado.record.sha256
    assert linha.origem == "pendrive"
    assert linha.tipo == "texto"
    assert linha.size_bytes == len("conteudo do doomsday\n")


def test_ingerir_duas_vezes_gera_uma_linha(
    tmp_path: Path, catalogo: SqlCatalog, engine: Engine
) -> None:
    """Idempotência através do catálogo persistente — o começo da Onda 4."""
    arquivo = tmp_path / "nota.txt"
    arquivo.write_text("mesmo conteudo\n")

    store = FakeObjectStore()
    clock = FixedClock()

    primeiro = ingest(
        IngestRequest(path=str(arquivo), origem="pendrive"),
        store=store,
        catalog=catalogo,
        clock=clock,
    )
    segundo = ingest(
        IngestRequest(path=str(arquivo), origem="pendrive"),
        store=store,
        catalog=catalogo,
        clock=clock,
    )

    with engine.connect() as conn:
        total = conn.execute(text("select count(*) from objects")).scalar_one()

    assert primeiro.duplicate is False
    assert segundo.duplicate is True
    assert total == 1
    assert store.escritas == 1


def test_origem_diferente_mesmo_conteudo_nao_duplica(
    tmp_path: Path, catalogo: SqlCatalog, engine: Engine
) -> None:
    """O hash manda, não a origem.

    Duas fontes que trazem o mesmo arquivo produzem **um** objeto. A proveniência
    registrada é a da primeira — e isso é consequência aceita da idempotência por
    conteúdo, não um bug.
    """
    arquivo = tmp_path / "relatorio.pdf"
    arquivo.write_bytes(b"%PDF-1.7 conteudo")

    store = FakeObjectStore()
    clock = FixedClock()

    ingest(
        IngestRequest(path=str(arquivo), origem="pendrive"),
        store=store,
        catalog=catalogo,
        clock=clock,
    )
    segundo = ingest(
        IngestRequest(path=str(arquivo), origem="email"),
        store=store,
        catalog=catalogo,
        clock=clock,
    )

    with engine.connect() as conn:
        total = conn.execute(text("select count(*) from objects")).scalar_one()
        origem_gravada = conn.execute(text("select origem from objects")).scalar_one()

    assert segundo.duplicate is True
    assert total == 1
    assert origem_gravada == "pendrive"


def test_metadados_chegam_ao_banco(
    tmp_path: Path, catalogo: SqlCatalog, engine: Engine
) -> None:
    arquivo = tmp_path / "dados.csv"
    arquivo.write_text("a,b\n1,2\n")

    ingest(
        IngestRequest(
            path=str(arquivo),
            origem="sensor",
            metadados={"equipamento": "estacao-1"},
        ),
        store=FakeObjectStore(),
        catalog=catalogo,
        clock=FixedClock(),
    )

    with engine.connect() as conn:
        metadados = conn.execute(text("select metadados from objects")).scalar_one()

    # `text()` não aplica o TypeDecorator: no PostgreSQL o JSON vem como dict,
    # no SQLite como string. Normalizar aqui mantém o teste válido nos dois
    # dialetos sem esconder a diferença.
    if isinstance(metadados, str):
        metadados = json.loads(metadados)

    assert metadados["nome_original"] == "dados.csv"
    assert metadados["equipamento"] == "estacao-1"
