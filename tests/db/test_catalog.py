"""Testes do adaptador de catálogo.

Exercitam a porta `Catalog` sobre SQL real. O invariante central é o `sha256`
único: é dele que depende a idempotência da ingestão (Onda 4).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from lakecore.db.catalog import SqlCatalog
from lakecore.errors import DuplicateObjectError
from lakecore.models import Record

SHA_A = "a" * 64
SHA_B = "b" * 64
MOMENTO = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


def _record(sha: str = SHA_A, **kwargs: object) -> Record:
    base = dict(
        sha256=sha,
        bucket="raw",
        key=f"raw/pendrive/texto/2026/11/18/{sha}",
        size=42,
        content_type="text/plain",
        origem="pendrive",
        tipo="texto",
        coletado_em=MOMENTO,
        metadados={"nome_original": "nota.txt"},
    )
    base.update(kwargs)
    return Record(**base)  # type: ignore[arg-type]


@pytest.fixture
def catalog(session_factory: sessionmaker) -> SqlCatalog:
    return SqlCatalog(session_factory)


def test_adiciona_e_recupera_por_sha(catalog: SqlCatalog) -> None:
    catalog.add(_record())

    recuperado = catalog.by_sha256(SHA_A)

    assert recuperado is not None
    assert recuperado.sha256 == SHA_A
    assert recuperado.origem == "pendrive"
    assert recuperado.metadados["nome_original"] == "nota.txt"


def test_sha_inexistente_devolve_none(catalog: SqlCatalog) -> None:
    assert catalog.by_sha256(SHA_B) is None


def test_segunda_insercao_do_mesmo_sha_levanta_duplicado(catalog: SqlCatalog) -> None:
    catalog.add(_record(sha=SHA_A))

    with pytest.raises(DuplicateObjectError) as exc:
        catalog.add(_record(sha=SHA_A))

    assert exc.value.sha256 == SHA_A


def test_duplicado_nao_deixa_sessao_suja(catalog: SqlCatalog) -> None:
    """Após o erro de unicidade, o catálogo continua utilizável.

    Sem `rollback` no caminho de erro, a próxima operação falharia com
    "current transaction is aborted" — falha em cascata difícil de diagnosticar.
    """
    catalog.add(_record(sha=SHA_A))
    with pytest.raises(DuplicateObjectError):
        catalog.add(_record(sha=SHA_A))

    catalog.add(_record(sha=SHA_B))

    assert catalog.by_sha256(SHA_B) is not None


def test_remover_devolve_true_e_apaga(catalog: SqlCatalog) -> None:
    catalog.add(_record())

    assert catalog.remover(SHA_A) is True
    assert catalog.by_sha256(SHA_A) is None


def test_remover_inexistente_devolve_false(catalog: SqlCatalog) -> None:
    assert catalog.remover(SHA_B) is False


def test_tamanho_negativo_e_barrado_pelo_banco(
    catalog: SqlCatalog, engine: Engine
) -> None:
    """O `CHECK` do schema é a última linha de defesa, não a primeira.

    Se uma migração futura remover a validação de domínio, o banco ainda recusa.
    """
    from sqlalchemy import text

    # `now()` não existe em SQLite; o timestamp é passado como parâmetro para
    # que o mesmo SQL rode nos dois dialetos.
    sql = (
        "insert into objects (sha256, bucket, key, size_bytes, content_type, "
        "origem, tipo, coletado_em, criado_em, metadados) "
        "values (:sha, 'raw', 'k', :size, 'text/plain', 'o', 't', :agora, "
        "        :agora, '{}')"
    )

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text(sql), {"sha": SHA_B, "size": -1, "agora": MOMENTO})


def test_metadados_json_sobrevivem_ao_roundtrip(catalog: SqlCatalog) -> None:
    metadados = {
        "nome_original": "relatorio.pdf",
        "tags": ["financeiro", "2026"],
        "aninhado": {"autor": "equipe", "paginas": 12},
    }
    catalog.add(_record(metadados=metadados))

    recuperado = catalog.by_sha256(SHA_A)

    assert recuperado is not None
    assert recuperado.metadados == metadados
