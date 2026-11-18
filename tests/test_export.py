"""Testes do export Parquet.

O QUE ESTES TESTES PROTEGEM:

o derivado é reconstruível (o `raw/` é o insubstituível), então corromper um
Parquet não é desastre. O que **não** é reconstruível é a confiança: se o export
perder um tipo ou uma linha em silêncio, o chat passa a responder errado com
cara de certo. É o mesmo risco do executor, em outro lugar.

Os três testes que mais importam:

1. **tipos sobrevivem** — `size_bytes` volta como número, não como texto. Se
   voltasse texto, `sum()` no derivado compararia strings e daria resultado
   absurdo sem erro nenhum.
2. **nenhuma linha se perde** — a contagem do Parquet é a do catálogo.
3. **tabela vazia ainda gera arquivo** — o consumidor não precisa tratar
   "não existe" e "vazio" como casos distintos.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from lakecore.db.models import Base
from lakecore.export import COLUNAS_OBJECTS, consultar, exportar


@pytest.fixture
def banco() -> Iterator[Engine]:
    eng = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    with eng.begin() as conn:
        for sha, origem, tipo, tamanho, status in [
            ("a" * 64, "whatsapp", "texto", 100, "cataloged"),
            ("b" * 64, "whatsapp", "foto", 200, "cataloged"),
            ("c" * 64, "email", "texto", 50, "failed"),
        ]:
            conn.execute(
                text(
                    "insert into objects (sha256, bucket, key, size_bytes, content_type,"
                    " origem, tipo, coletado_em, criado_em, metadados, status) values"
                    " (:sha,'raw',:k,:tam,'text/plain',:orig,:tipo,'2026-01-01','2026-01-01','{}',:st)"
                ),
                {"sha": sha, "k": f"raw/{origem}/{sha[:4]}", "tam": tamanho,
                 "orig": origem, "tipo": tipo, "st": status},
            )
        conn.execute(
            text(
                "insert into uploads (origem, total, aceitos, duplicados, falhas, iniciado_em)"
                " values ('whatsapp', 2, 1, 1, 0, '2026-01-01')"
            )
        )
    try:
        yield eng
    finally:
        eng.dispose()


class TestExport:
    def test_escreve_os_dois_arquivos(self, banco: Engine, tmp_path: Path) -> None:
        resultado = exportar(banco, tmp_path)
        nomes = {c.name for c in resultado.caminhos}
        assert nomes == {"objects.parquet", "uploads.parquet"}
        assert all(c.exists() for c in resultado.caminhos)

    def test_conta_as_linhas(self, banco: Engine, tmp_path: Path) -> None:
        resultado = exportar(banco, tmp_path)
        assert resultado.linhas_por_tabela == {"objects": 3, "uploads": 1}

    def test_nenhuma_linha_se_perde(self, banco: Engine, tmp_path: Path) -> None:
        """O derivado tem que ter exatamente o que o catálogo tem."""
        resultado = exportar(banco, tmp_path)
        objects = tmp_path / "objects.parquet"
        linhas = consultar(objects, "select count(*) from {parquet}")
        assert linhas[0][0] == resultado.linhas_por_tabela["objects"] == 3

    def test_tipos_sobrevivem(self, banco: Engine, tmp_path: Path) -> None:
        """`size_bytes` tem que voltar NUMÉRICO.

        Se voltasse texto, `sum()` no derivado compararia strings: o resultado
        seria absurdo sem erro nenhum. Este é o defeito que a inferência
        automática esconde.
        """
        exportar(banco, tmp_path)
        soma = consultar(tmp_path / "objects.parquet", "select sum(size_bytes) from {parquet}")
        assert soma[0][0] == 350, f"esperado 350 (int), veio {soma[0][0]!r}"

    def test_soma_numerica_nao_concatena(self, banco: Engine, tmp_path: Path) -> None:
        """Prova complementar: 100+200+50=350, não '100200 50'."""
        exportar(banco, tmp_path)
        tipo = consultar(
            tmp_path / "objects.parquet",
            "select typeof(sum(size_bytes)) from {parquet}",
        )
        assert "INT" in str(tipo[0][0]).upper()

    def test_metadados_fica_como_texto(self, banco: Engine, tmp_path: Path) -> None:
        """JSON do usuário não vira estrutura: o formato do dado é dele."""
        exportar(banco, tmp_path)
        de_teste = consultar(
            tmp_path / "objects.parquet",
            "select typeof(metadados) from {parquet} limit 1",
        )
        assert "VARCHAR" in str(de_teste[0][0]).upper()

    def test_tabela_vazia_ainda_gera_arquivo(self, banco: Engine, tmp_path: Path) -> None:
        """'não existe' e 'vazio' são o mesmo caso para o consumidor."""
        with banco.begin() as conn:
            conn.execute(text("delete from uploads"))
        resultado = exportar(banco, tmp_path)
        assert resultado.linhas_por_tabela["uploads"] == 0
        assert (tmp_path / "uploads.parquet").exists()
        assert consultar(tmp_path / "uploads.parquet", "select count(*) from {parquet}")[0][0] == 0

    def test_colunas_sao_as_declaradas(self, banco: Engine, tmp_path: Path) -> None:
        """Uma coluna nova no catálogo não entra no derivado sem alguém decidir."""
        exportar(banco, tmp_path)
        con = duckdb.connect(":memory:")
        try:
            descricao = con.execute(
                f"describe select * from read_parquet('{tmp_path / 'objects.parquet'}')"
            ).fetchall()
        finally:
            con.close()
        assert [d[0] for d in descricao] == list(COLUNAS_OBJECTS)

    def test_export_e_deterministico(self, banco: Engine, tmp_path: Path) -> None:
        """Mesmo estado → mesmas linhas na mesma ordem."""
        exportar(banco, tmp_path)
        primeira = consultar(tmp_path / "objects.parquet", "select sha256 from {parquet}")
        exportar(banco, tmp_path)
        segunda = consultar(tmp_path / "objects.parquet", "select sha256 from {parquet}")
        assert primeira == segunda


class TestNaoDeixaLixo:
    def test_sem_arquivo_temporario_no_fim(self, banco: Engine, tmp_path: Path) -> None:
        """Sobrescrita atômica: o temporário sai de cena ou o Parquet é ruim."""
        exportar(banco, tmp_path)
        temporarios = list(tmp_path.glob("*.tmp")) + list(tmp_path.glob(".*.tmp"))
        assert temporarios == []

    def test_sobrescreve_sem_duplicar(self, banco: Engine, tmp_path: Path) -> None:
        exportar(banco, tmp_path)
        resultado = exportar(banco, tmp_path)
        assert len(resultado.caminhos) == 2
        assert len(list(tmp_path.glob("*.parquet"))) == 2


class TestFalhaVisivel:
    def test_tabela_inexistente_falha_alto(self, banco: Engine, tmp_path: Path) -> None:
        """Export silencioso de tabela que não existe viraria 'acervo vazio'."""
        with pytest.raises(Exception):
            exportar(banco, tmp_path, tabelas=("nao_existe",))
