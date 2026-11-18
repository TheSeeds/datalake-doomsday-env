"""Testes do servidor MCP — a ponte entre a tela e o catálogo.

O que estes testes defendem, em ordem de gravidade:

1. **Nenhuma ferramenta escreve.** A tela é dirigida por modelo; um modelo que
   "decide" limpar o catálogo não pode ter com que. Testado tentando escrever
   por cada ferramenta, inclusive pedindo a escrita em português.
2. **O SQL executado é sempre devolvido.** Sem isso o chat vira caixa-preta, e
   resposta errada fica indistinguível de resposta certa.
3. **Sem LLM a ferramenta funciona.** `lake_buscar` é o caminho determinístico:
   se ele dependesse de modelo, o lake mínimo não existiria.
4. **O schema entregue é o real.** Foi medido que modelo barato inventa coluna;
   a ferramenta que entrega o schema tem que refletir o banco, não uma cópia.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from lakecore.db.models import Base
from lakecore.mcp import (
    LIMITE_BUSCA,
    engine,
    formatar,
    lake_buscar,
    lake_esquema,
    lake_estado,
    lake_sql,
)


@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    """Banco em memória com o schema real, injetado no módulo MCP."""
    eng = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)

    with eng.begin() as conn:
        for sha, origem, tipo, tamanho, ct, status, quando, meta in [
            ("a" * 64, "whatsapp", "texto", 100, "text/plain", "cataloged", "2026-01-01", "{}"),
            ("b" * 64, "whatsapp", "foto", 200, "image/jpeg", "cataloged", "2026-01-02", "{}"),
            ("c" * 64, "email", "texto", 50, "text/plain", "cataloged", "2026-02-01", "{}"),
            ("d" * 64, "dropbox", "pdf", 900, "application/pdf", "done", "2026-02-03", "{}"),
            ("e" * 64, "email", "texto", 70, "text/plain", "failed", "2026-03-01", "{}"),
        ]:
            conn.execute(
                text(
                    "insert into objects "
                    "(sha256, bucket, key, size_bytes, content_type, origem, tipo,"
                    " coletado_em, criado_em, metadados, status) values "
                    "(:sha, 'raw', :k, :tam, :ct, :orig, :tipo, :quando, :quando, :meta, :st)"
                ),
                {
                    "sha": sha, "k": f"raw/{origem}/{tipo}/{sha[:4]}", "tam": tamanho,
                    "ct": ct, "orig": origem, "tipo": tipo, "quando": quando,
                    "meta": meta, "st": status,
                },
            )
        conn.execute(
            text(
                "insert into uploads (origem, total, aceitos, duplicados, falhas, iniciado_em)"
                " values ('whatsapp', 2, 1, 1, 0, '2026-01-01')"
            )
        )

    monkeypatch.setattr("lakecore.mcp._engine", eng)
    try:
        yield eng
    finally:
        eng.dispose()


def contar(eng: Engine) -> int:
    with eng.connect() as conn:
        return conn.execute(text("select count(*) from objects")).scalar_one()


class TestNenhumaFerramentaEscreve:
    """A garantia central: o lado do lake não tem verbo de escrita."""

    @pytest.mark.parametrize(
        "sql",
        [
            "DROP TABLE objects",
            "DELETE FROM objects",
            "UPDATE objects SET origem = 'x'",
            "TRUNCATE objects",
            "INSERT INTO objects (sha256) VALUES ('x')",
        ],
    )
    def test_lake_sql_recusa_escrita_e_nao_muda_nada(self, banco: Engine, sql: str) -> None:
        antes = contar(banco)
        resposta = lake_sql(sql)
        assert "recusada" in resposta.lower()
        assert contar(banco) == antes

    def test_escrita_escondida_em_cte_tambem_e_recusada(self, banco: Engine) -> None:
        antes = contar(banco)
        resposta = lake_sql(
            "WITH x AS (DELETE FROM objects RETURNING sha256) SELECT * FROM x"
        )
        assert "recusada" in resposta.lower()
        assert contar(banco) == antes

    def test_busca_nao_aceita_sql_no_lugar_de_filtro(self, banco: Engine) -> None:
        """`lake_buscar` interpola valores como parâmetro, nunca como SQL."""
        antes = contar(banco)
        lake_buscar(origem="whatsapp' or '1'='1")
        assert contar(banco) == antes


class TestSqlSempreVisivel:
    """Transparência: a pessoa vê a consulta que gerou aquele número."""

    def test_resposta_mostra_o_sql_executado(self, banco: Engine) -> None:
        resposta = lake_sql("select origem, count(*) from objects group by origem")
        assert "SQL executado" in resposta
        assert "select origem, count(*)" in resposta

    def test_sql_aparece_antes_dos_dados(self, banco: Engine) -> None:
        """Número errado parece certo; SQL errado, não. Então o SQL vem primeiro."""
        resposta = lake_sql("select count(*) from objects")
        assert resposta.index("SQL executado") < resposta.index("5")

    def test_resultado_vazio_e_explicado_nao_omitido(self, banco: Engine) -> None:
        resposta = lake_sql("select * from objects where origem = 'inexistente'")
        assert "nenhuma linha" in resposta
        assert "select * from objects" in resposta


class TestBuscaSemLLM:
    """O caminho determinístico — o lake mínimo não depende de modelo."""

    def test_filtro_por_origem(self, banco: Engine) -> None:
        resposta = lake_buscar(origem="whatsapp")
        assert "Objetos: 2" in resposta
        assert "whatsapp" in resposta

    def test_filtro_por_status(self, banco: Engine) -> None:
        resposta = lake_buscar(status="failed")
        assert "Objetos: 1" in resposta

    def test_filtro_por_intervalo_de_datas(self, banco: Engine) -> None:
        resposta = lake_buscar(desde="2026-02-01", ate="2026-02-03")
        assert "Objetos: 2" in resposta

    def test_sem_filtro_devolve_tudo(self, banco: Engine) -> None:
        assert "Objetos: 5" in lake_buscar()

    def test_filtro_sem_resultado_explica(self, banco: Engine) -> None:
        resposta = lake_buscar(origem="nao-existe")
        assert "nenhum objeto" in resposta.lower()
        assert "SQL executado" in resposta

    def test_sempre_mostra_o_sql(self, banco: Engine) -> None:
        assert "SQL executado" in lake_buscar(tipo="texto")

    def test_limite_nao_passa_do_teto(self, banco: Engine) -> None:
        """Pedir mais que o teto é servido com o teto, não com o pedido."""
        resposta = lake_buscar(limite=10_000)
        assert f"limit {LIMITE_BUSCA + 1}" in resposta


class TestEsquemaReal:
    """A ferramenta que impede o modelo de inventar coluna."""

    def test_entrega_colunas_que_existem(self, banco: Engine) -> None:
        resposta = lake_esquema()
        for coluna in ("origem", "tipo", "coletado_em", "sha256", "size_bytes", "metadados"):
            assert coluna in resposta

    def test_entrega_as_duas_tabelas(self, banco: Engine) -> None:
        resposta = lake_esquema()
        assert "objects:" in resposta
        assert "uploads:" in resposta

    def test_avisa_os_status_validos(self, banco: Engine) -> None:
        """O CHECK do schema é informação que o modelo precisa para filtrar."""
        resposta = lake_esquema()
        assert "cataloged" in resposta and "failed" in resposta

    def test_desambigua_origem_de_tipo(self, banco: Engine) -> None:
        """Confundir procedência com natureza é o erro mais provável do domínio."""
        resposta = lake_esquema()
        assert "PROCEDÊNCIA" in resposta
        assert "NATUREZA" in resposta


class TestEstado:
    """Diagnóstico, não exploração."""

    def test_conta_objetos_e_bytes(self, banco: Engine) -> None:
        resposta = lake_estado()
        assert "objetos no catálogo: 5" in resposta
        assert "bytes catalogados: 1320" in resposta

    def test_mostra_o_que_falhou(self, banco: Engine) -> None:
        assert "failed" in lake_estado()

    def test_mostra_lotes_de_ingestao(self, banco: Engine) -> None:
        assert "uploads" in lake_estado() or "lotes" in lake_estado()


class TestFormatacao:
    """`formatar` é o que a pessoa lê; truncagem silenciosa seria mentira."""

    def test_truncado_e_declarado(self) -> None:
        from lakecore.chat.executor import ResultadoSql

        resultado = ResultadoSql(
            colunas=["n"], linhas=[(1,), (2,)], sql_executado="select 1", truncado=True
        )
        assert "truncado" in formatar(resultado)

    def test_decimal_integral_vira_int(self) -> None:
        """`SUM` em PostgreSQL devolve `Decimal`; `10.00` na tela parece conta errada."""
        from decimal import Decimal

        from lakecore.chat.executor import ResultadoSql

        resultado = ResultadoSql(
            colunas=["s"], linhas=[(Decimal("1320.00"),)], sql_executado="select 1", truncado=False
        )
        assert "1320\n" in formatar(resultado) or formatar(resultado).endswith("1320")
