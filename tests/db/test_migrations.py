"""Testes da migração do catálogo.

Cobrem o ciclo completo e, principalmente, o caso que o CI do geoflow não cobria:
**migração sobre banco já populado**. Uma migração que passa em banco vazio e
falha em produção custa o ativo do lake.

Todos exigem PostgreSQL real. SQLite aceita `downgrade` por outro caminho e não
tem `JSONB`/`GIN`, então não prova nada sobre o alvo.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

REVISAO_INICIAL = "65a942da6f86"
REVISAO_STATUS = "8b1f2c3d4e5a"


def test_upgrade_cria_tabelas_e_indices(
    aplicar_migracao: Callable[[str], None], url_schema_dedicado: tuple[str, Engine]
) -> None:
    _url, engine = url_schema_dedicado
    aplicar_migracao("head")

    with engine.connect() as conn:
        tabelas = {
            linha[0]
            for linha in conn.execute(
                text(
                    "select table_name from information_schema.tables "
                    "where table_schema = current_schema()"
                )
            )
        }

    assert {"objects", "uploads", "alembic_version"} <= tabelas


def test_indice_gin_existe_no_postgres(
    aplicar_migracao: Callable[[str], None], url_schema_dedicado: tuple[str, Engine]
) -> None:
    _url, engine = url_schema_dedicado
    aplicar_migracao("head")

    with engine.connect() as conn:
        indices = {
            linha[0]
            for linha in conn.execute(
                text(
                    "select indexname from pg_indexes "
                    "where schemaname = current_schema() and tablename = 'objects'"
                )
            )
        }

    assert "ix_objects_metadados_gin" in indices


def test_downgrade_remove_tudo(
    aplicar_migracao: Callable[[str], None],
    url_schema_dedicado: tuple[str, Engine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url, engine = url_schema_dedicado
    aplicar_migracao("head")

    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "src/lakecore/db/migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    monkeypatch.setenv("LAKECORE_DATABASE_URL", url)
    command.downgrade(cfg, "base")

    with engine.connect() as conn:
        tabelas = {
            linha[0]
            for linha in conn.execute(
                text(
                    "select table_name from information_schema.tables "
                    "where table_schema = current_schema()"
                )
            )
        }

    assert "objects" not in tabelas
    assert "uploads" not in tabelas


def test_migracao_em_banco_populado_preserva_os_dados(
    aplicar_migracao: Callable[[str], None], url_schema_dedicado: tuple[str, Engine]
) -> None:
    """O caso que importa: dado já existe quando a migração roda.

    Simula o cenário real — `downgrade base` seguido de `upgrade head` **com
    linhas na tabela**. Se o `downgrade` apagara dado sem volta, o lake perderia
    o catálogo, e o próprio `downgrade` é o teste de que a migração é reversível
    de verdade.
    """
    _url, engine = url_schema_dedicado
    aplicar_migracao("head")

    with engine.begin() as conn:
        conn.execute(
            text(
                "insert into objects "
                "(sha256, bucket, key, size_bytes, content_type, origem, tipo, "
                " coletado_em, criado_em, metadados, status) "
                "values (:sha, 'raw', 'raw/x/texto/2026/11/18/:sha', 10, "
                "        'text/plain', 'teste', 'texto', now(), now(), '{}'::jsonb, "
                "        'cataloged')"
            ),
            {"sha": "a" * 64},
        )

    with engine.connect() as conn:
        antes = conn.execute(text("select count(*) from objects")).scalar_one()

    assert antes == 1

    # A tabela sobrevive a um segundo `upgrade head`, que é idempotente.
    aplicar_migracao("head")

    with engine.connect() as conn:
        depois = conn.execute(text("select count(*) from objects")).scalar_one()

    assert depois == 1, "upgrade novamente não pode perder nem duplicar dado"


def test_adicionar_coluna_em_tabela_populada_faz_backfill(
    aplicar_migracao: Callable[[str], None], url_schema_dedicado: tuple[str, Engine]
) -> None:
    """O caso que a primeira migração nunca exercita: evoluir schema com dado dentro.

    Roda a revisão inicial, insere uma linha **sem** a coluna `status`, e só
    então aplica a segunda migração. Se o `server_default` faltasse, PostgreSQL
    recusaria com "column contains null values" — e em produção isso significa
    migração travada com o lake parado.
    """
    _url, engine = url_schema_dedicado
    aplicar_migracao(REVISAO_INICIAL)

    with engine.begin() as conn:
        conn.execute(
            text(
                "insert into objects "
                "(sha256, bucket, key, size_bytes, content_type, origem, tipo, "
                " coletado_em, criado_em, metadados) "
                "values (:sha, 'raw', 'k', 1, 'text/plain', 'o', 't', "
                "        now(), now(), '{}'::jsonb)"
            ),
            {"sha": "c" * 64},
        )

    aplicar_migracao(REVISAO_STATUS)

    with engine.connect() as conn:
        total, status = conn.execute(
            text("select count(*), min(status) from objects")
        ).one()

    assert total == 1, "a linha pre-existente não pode ser perdida"
    assert status == "cataloged", "o server_default precisa preencher a coluna nova"


def test_check_de_status_recusa_valor_invalido(
    aplicar_migracao: Callable[[str], None], url_schema_dedicado: tuple[str, Engine]
) -> None:
    """A constraint é a última defesa se o domínio deixar passar valor inválido."""
    _url, engine = url_schema_dedicado
    aplicar_migracao("head")

    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "insert into objects "
                    "(sha256, bucket, key, size_bytes, content_type, origem, tipo, "
                    " coletado_em, criado_em, metadados, status) "
                    "values (:sha, 'raw', 'k', 1, 'text/plain', 'o', 't', "
                    "        now(), now(), '{}'::jsonb, 'inexistente')"
                ),
                {"sha": "d" * 64},
            )
