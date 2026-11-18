"""Testes do executor SQL — a defesa antes do chat existir.

Regra de escrita: cada teste tenta **uma forma de destruir o lake** e espera ser
recusado. Se algum passar, o chat não pode ser construído.

A lista de ataques não é teórica: são as formas pelas quais um modelo de
linguagem erra ao gerar SQL — escrever quando devia ler, encadear statements,
esconder escrita dentro de CTE, e varrer tabela inteira.
"""

from __future__ import annotations

import pytest
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from lakecore.chat.executor import (
    LIMITE_PADRAO,
    SqlRecusado,
    executar,
    validar,
)


class TestAllowlist:
    """Só leitura passa. Qualquer escrita é recusada na análise sintática."""

    @pytest.mark.parametrize(
        "sql",
        [
            "DROP TABLE objects",
            "drop table objects",
            "DELETE FROM objects",
            "TRUNCATE objects",
            "UPDATE objects SET origem = 'x'",
            "INSERT INTO objects VALUES (1)",
            "ALTER TABLE objects ADD COLUMN x int",
            "CREATE TABLE x (a int)",
            "GRANT ALL ON objects TO public",
            "VACUUM objects",
            "COPY objects TO '/tmp/x'",
        ],
    )
    def test_escrita_e_recusada(self, sql: str) -> None:
        with pytest.raises(SqlRecusado):
            validar(sql)

    @pytest.mark.parametrize("sql", ["SELECT 1", "select 1", "  SELECT 1  "])
    def test_select_passa(self, sql: str) -> None:
        assert validar(sql)

    def test_with_select_passa(self) -> None:
        sql = "WITH t AS (SELECT origem FROM objects) SELECT * FROM t"

        assert validar(sql)

    def test_with_escondendo_delete_e_recusado(self) -> None:
        """A allowlist de primeira palavra não alcança isso: `WITH` é lícito.

        Por isso existe a checagem específica — sem ela, um modelo poderia
        gerar um CTE com `DELETE ... RETURNING *` e ver "resultado", achando
        que fez uma consulta.
        """
        sql = "WITH x AS (DELETE FROM objects RETURNING *) SELECT * FROM x"

        with pytest.raises(SqlRecusado, match="escrita"):
            validar(sql)

    def test_with_escondendo_update_e_recusado(self) -> None:
        sql = "WITH x AS (UPDATE objects SET tipo='x' RETURNING *) SELECT * FROM x"

        with pytest.raises(SqlRecusado, match="escrita"):
            validar(sql)


class TestStatementUnico:
    def test_dois_statements_recusados(self) -> None:
        with pytest.raises(SqlRecusado, match="apenas um statement"):
            validar("SELECT 1; DROP TABLE objects")

    def test_ponto_e_virgula_final_e_aceito(self) -> None:
        assert validar("SELECT 1;")

    def test_comentario_com_ponto_e_virgula_nao_engana(self) -> None:
        """`SELECT 1 -- ; DROP TABLE x` é UMA consulta com um comentário."""
        assert validar("SELECT 1 -- ; DROP TABLE objects")

    def test_comentario_mascarando_segundo_statement_e_recusado(self) -> None:
        sql = "SELECT 1; --\nDROP TABLE objects"

        with pytest.raises(SqlRecusado):
            validar(sql)

    def test_statement_vazio_recusado(self) -> None:
        for vazio in ("", "   ", "-- só comentário", ";\n"):
            with pytest.raises(SqlRecusado):
                validar(vazio)


class TestNaoRecusaFalsoPositivo:
    """Buscar substring é o erro clássico; estes provam que não faço isso."""

    def test_coluna_chamada_drop_passa(self) -> None:
        assert validar("SELECT drop_reason FROM events")

    def test_tabela_com_nome_proibido_passa(self) -> None:
        assert validar("SELECT * FROM delete_log")

    def test_string_contendo_drop_passa(self) -> None:
        assert validar("SELECT 'DROP TABLE x' AS exemplo")


class TestExecucao:
    @pytest.fixture
    def engine(self) -> Iterator[Engine]:
        eng = create_engine("sqlite+pysqlite:///:memory:", future=True)
        with eng.begin() as conn:
            conn.exec_driver_sql(
                "create table objects (id int, origem text, tipo text)"
            )
            conn.exec_driver_sql(
                "insert into objects values "
                "(1,'pendrive','texto'),(2,'email','pdf'),(3,'pendrive','pdf')"
            )
        # `dispose` no teardown: sem isso o `ResourceWarning` de conexão sqlite
        # aberta vira erro, porque o projeto roda com `filterwarnings = error`.
        try:
            yield eng
        finally:
            eng.dispose()

    def test_select_simples(self, engine: Engine) -> None:
        r = executar(engine, "SELECT origem, tipo FROM objects ORDER BY id")

        assert r.colunas == ["origem", "tipo"]
        assert len(r.linhas) == 3
        assert r.linhas[0] == ("pendrive", "texto")
        assert r.truncado is False

    def test_agregacao(self, engine: Engine) -> None:
        r = executar(
            engine,
            "SELECT origem, count(*) as n FROM objects GROUP BY origem ORDER BY n DESC",
        )

        assert r.colunas == ["origem", "n"]
        assert ("pendrive", 2) in r.linhas

    def test_limite_e_forcado_quando_ausente(self, engine: Engine) -> None:
        r = executar(engine, "SELECT * FROM objects", limite=2)

        assert len(r.linhas) == 2
        assert r.truncado is True, "deve sinalizar que havia mais linhas"

    def test_limite_explicito_menor_e_respeitado(self, engine: Engine) -> None:
        r = executar(engine, "SELECT * FROM objects LIMIT 1", limite=100)

        assert len(r.linhas) == 1
        assert "limit 1" in r.sql_executado.lower()

    def test_sql_executado_e_devolvido(self, engine: Engine) -> None:
        """O usuário precisa VER o que foi consultado.

        Sem isso, "conversar com os dados" vira "confiar no chatbot".
        """
        r = executar(engine, "SELECT origem FROM objects")

        assert "select" in r.sql_executado.lower()
        assert "objects" in r.sql_executado

    def test_recusa_antes_de_tocar_no_banco(self, engine: Engine) -> None:
        """`executar` com SQL proibido levanta sem executar nada."""
        with pytest.raises(SqlRecusado):
            executar(engine, "DROP TABLE objects")

        r = executar(engine, "SELECT count(*) FROM objects")
        assert r.linhas == [(3,)], "a tabela tem que continuar intacta"

    def test_select_que_falha_no_banco_propaga(self, engine: Engine) -> None:
        """Erro de SQL gerado (coluna inexistente) deve chegar ao chamador.

        Esconder isso produziria "nenhum resultado" em vez de "o modelo errou".
        """
        from sqlalchemy.exc import OperationalError

        with pytest.raises(OperationalError):
            executar(engine, "SELECT coluna_que_nao_existe FROM objects")


class TestConstantes:
    def test_limite_padrao_e_baixo(self) -> None:
        """O chat responde em texto, não exporta dados.

        Teto alto convidaria a varrer tabela inteira e travar a resposta.
        """
        assert LIMITE_PADRAO <= 500
