"""Testes do restore drill.

O QUE ESTES TESTES PROTEGEM:

o drill existe para responder "o backup volta a virar catálogo?". Um drill que
sempre diz "provado" é pior que nenhum: transforma esperança em certificado.
Então cada teste aqui tenta **produzir um falso positivo** — fazer o drill dizer
que está tudo certo com um restore incompleto — e espera ser pego.

O caso central é a divergência com **mesma contagem e conteúdo diferente**. É o
cenário que uma comparação ingênua (`count(*)`) aprova e que na prática significa
"restaurei o acervo errado".
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docker" / "backup"))

import restore_drill as rd  # noqa: E402


class TestEscolherDump:
    """Escolher o dump errado é o erro mais fácil de cometer e o mais silencioso."""

    def test_escolhe_o_mais_recente_pelo_nome(self) -> None:
        chaves = [
            "postgres/lakecore-20261117T141150Z.sql.gz",
            "postgres/lakecore-20261118T141150Z.sql.gz",
            "postgres/lakecore-20261116T141150Z.sql.gz",
        ]
        assert rd.escolher_ultimo_backup(chaves) == (
            "postgres/lakecore-20261118T141150Z.sql.gz"
        )

    def test_ignora_arquivos_que_nao_sao_dump(self) -> None:
        chaves = [
            "postgres/leiame.txt",
            "postgres/lakecore-20261118T141150Z.sql.gz",
            "postgres/.gitkeep",
        ]
        assert rd.escolher_ultimo_backup(chaves).endswith(".sql.gz")

    def test_sem_dump_nenhum_falha_alto(self) -> None:
        """A ausência de backup É o resultado, não um caso a ignorar."""
        with pytest.raises(rd.DrillFalhou, match="não há nenhum"):
            rd.escolher_ultimo_backup(["postgres/leiame.txt"])

    def test_lista_vazia_falha_alto(self) -> None:
        with pytest.raises(rd.DrillFalhou):
            rd.escolher_ultimo_backup([])


class TestAssinatura:
    """Parsing da saída, incluindo a forma como o banco vazio responde."""

    def test_le_duas_tabelas(self) -> None:
        saida = "objects|11|abc123\nuploads|2|def456\n"
        assert rd.assinatura(saida) == {
            "objects": ("11", "abc123"),
            "uploads": ("2", "def456"),
        }

    def test_aceita_linha_em_branco_no_fim(self) -> None:
        assert rd.assinatura("objects|0|(vazio)\n\n")["objects"] == ("0", "(vazio)")

    def test_linha_malformada_e_erro_explicito(self) -> None:
        """Silenciar aqui viraria 'nenhuma tabela' e o drill passaria vazio."""
        with pytest.raises(rd.DrillFalhou, match="inesperada"):
            rd.assinatura("objects|11\n")


class TestComparacao:
    """O critério do drill. Cada teste tenta um falso positivo."""

    def test_identicos_nao_tem_problema(self) -> None:
        a = {"objects": ("11", "abc"), "uploads": ("2", "def")}
        assert rd.comparar(a, dict(a)) == []

    def test_contagem_diferente_e_pega(self) -> None:
        original = {"objects": ("11", "abc")}
        restaurado = {"objects": ("10", "abc")}
        problemas = rd.comparar(original, restaurado)
        assert len(problemas) == 1
        assert "contagem diverge" in problemas[0]

    def test_mesma_contagem_conteudo_diferente_e_pega(self) -> None:
        """O caso que `count(*)` sozinho aprova e que significa acervo errado."""
        original = {"objects": ("11", "abc")}
        restaurado = {"objects": ("11", "xyz")}
        problemas = rd.comparar(original, restaurado)
        assert len(problemas) == 1
        assert "conteúdo diverge" in problemas[0]

    def test_tabela_ausente_no_restaurado_e_pega(self) -> None:
        """Restore parcial não pode passar como completo."""
        original = {"objects": ("11", "abc"), "uploads": ("2", "def")}
        restaurado = {"objects": ("11", "abc")}
        problemas = rd.comparar(original, restaurado)
        assert len(problemas) == 1
        assert "uploads" in problemas[0]
        assert "ausente" in problemas[0]

    def test_tabela_so_no_restaurado_tambem_e_divergencia(self) -> None:
        assert rd.comparar({"objects": ("1", "a")}, {"objects": ("1", "a"), "x": ("1", "b")})

    def test_banco_restaurado_vazio_nao_passa(self) -> None:
        """Restore que não restaurou nada: o falso positivo mais provável."""
        problemas = rd.comparar({"objects": ("11", "abc")}, {})
        assert problemas and "ausente" in problemas[0]


class TestSemTocarNoOriginal:
    """O drill nunca escreve no banco de origem. Se escrevesse, seria o desastre."""

    def test_nenhum_comando_usa_o_banco_original_para_escrita(self) -> None:
        executados: list[list[str]] = []

        class FakeS3:
            def list_objects_v2(self, **_: object) -> dict:
                return {"Contents": [{"Key": "postgres/d.sql.gz", "Size": 10}]}

            def download_file(self, *_: object) -> None:
                import gzip

                Path("/tmp/d.sql.gz").write_bytes(gzip.compress(b"PGDMP" + b"x" * 40))

        def fake_run(comando: list[str], **_: object):
            executados.append(list(comando))

            class R:
                returncode = 0
                stdout = "objects|1|abc\nuploads|0|(vazio)\n"
                stderr = ""

            return R()

        def fake_psql(run, dsn, banco, sql):  # noqa: ANN001, ANN202
            return "objects|1|abc\nuploads|0|(vazio)\n"

        rd.boto3.client = lambda *a, **k: FakeS3()  # type: ignore[assignment]
        monkeypatch_env = {
            "GARAGE_S3_ENDPOINT": "http://garage:3900",
            "POSTGRES_USER": "lakecore",
            "POSTGRES_DB": "lakecore",
            "S3_ACCESS_KEY": "k",
            "S3_SECRET_KEY": "s",
        }
        import os

        antigo = {k: os.environ.get(k) for k in monkeypatch_env}
        os.environ.update(monkeypatch_env)
        original_psql = rd.psql
        rd.psql = fake_psql  # type: ignore[assignment]
        try:
            rd.main(["restore_drill.py"], run=rd.Runner(fake_run))
        finally:
            rd.psql = original_psql  # type: ignore[assignment]
            for k, v in antigo.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

        # Nenhum comando pode ter alvo `-d lakecore` com escrita: só o banco de
        # rascunho recebe `-c`. A leitura do original acontece por SELECT.
        escritas_no_original = [
            c
            for c in executados
            if "-d" in c
            and c[c.index("-d") + 1] == "lakecore"
            and "-c" in c
        ]
        assert escritas_no_original == [], (
            f"o drill escreveu no banco original: {escritas_no_original}"
        )
