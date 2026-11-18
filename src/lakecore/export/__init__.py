"""Exporta o catálogo para Parquet — o que o chat consulta sem bater no OLTP.

POR QUE ESTE MÓDULO EXISTE:

o chat (`lake_sql`) consulta o PostgreSQL direto. Hoje isso é instantâneo porque
o acervo tem 11 linhas. Com dezenas de milhares, cada pergunta do usuário vira
uma varredura no banco transacional — e o banco que serve a ingestão passa a
competir com a leitura analítica.

O Parquet resolve três coisas de uma vez:

1. **Separar leitura de escrita.** O OLTP fica para ingestão; a pergunta vai
   para um arquivo colunar imutável.
2. **O derivado é reconstruível.** O que é insubstituível é o `raw/` (ADR-005).
   Se o Parquet corromper, roda de novo — por isso ele não precisa de backup.
3. **Funciona offline.** Um `.parquet` é um arquivo; não depende de serviço vivo.

POR QUE `duckdb` E NÃO `pyarrow`:

Um único pacote de 31 MB escreve **e** consulta Parquet; `pyarrow` faria só
escrever e custaria 42 MB. Num bundle offline que precisa caber em pendrive, um
pacote fazendo os dois trabalhos vence dois pacotes fazendo um cada.

DECISÕES QUE NÃO SÃO DE ESTILO:

- **Um arquivo por tabela, com sobrescrita atômica.** Escrever direto no destino
  deixa um Parquet truncado se o processo morrer no meio; renomear é atômico
  dentro do mesmo filesystem.
- **Nada de `SELECT *`.** As colunas são nomeadas uma a uma: uma coluna nova no
  catálogo não muda o schema do derivado sem alguém decidir.
- **`metadados` vai como JSON em texto**, não como estrutura. O formato do
  conteúdo é do usuário, não nosso; achatar poria a inferência no lugar errado.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
from sqlalchemy import text
from sqlalchemy.engine import Engine

log = logging.getLogger(__name__)

#: Colunas exportadas de `objects`, na ordem do Parquet.
#: `id` fica de fora de propósito: é surrogate key do PostgreSQL, não tem
#: significado fora dele. O identificador do objeto é `sha256`.
COLUNAS_OBJECTS = (
    "sha256",
    "bucket",
    "key",
    "size_bytes",
    "content_type",
    "origem",
    "tipo",
    "coletado_em",
    "criado_em",
    "metadados",
    "status",
)

#: Colunas exportadas de `uploads`.
COLUNAS_UPLOADS = (
    "origem",
    "total",
    "aceitos",
    "duplicados",
    "falhas",
    "iniciado_em",
    "concluido_em",
    "erro",
)

#: Tipo de cada coluna no Parquet. Escrever tudo como `varchar` "funcionaria" —
#: e seria o defeito: `size_bytes` viraria texto e `sum()` no derivado passaria a
#: comparar strings. O tipo tem que vir daqui, declarado, e não inferido das
#: linhas: coluna vazia não tem tipo para inferir.
#:
#: `bigint` para tamanhos e contagens; `varchar` para identificadores e nomes;
#: `timestamp` para os instantes. `metadados` fica `varchar` porque é JSON do
#: usuário: achatar em estrutura seria impor schema ao dado heterogêneo.
TIPOS = {
    "sha256": "varchar",
    "bucket": "varchar",
    "key": "varchar",
    "size_bytes": "bigint",
    "content_type": "varchar",
    "origem": "varchar",
    "tipo": "varchar",
    "coletado_em": "timestamp",
    "criado_em": "timestamp",
    "metadados": "varchar",
    "status": "varchar",
    "total": "integer",
    "aceitos": "integer",
    "duplicados": "integer",
    "falhas": "integer",
    "iniciado_em": "timestamp",
    "concluido_em": "timestamp",
    "erro": "varchar",
}


@dataclass(frozen=True, slots=True)
class ResultadoExport:
    """O que foi escrito, para quem chama poder reportar sem inventar."""

    caminhos: tuple[Path, ...]
    linhas_por_tabela: dict[str, int]
    bytes_totais: int


def _ler_tabela(engine: Engine, tabela: str, colunas: tuple[str, ...]) -> list[tuple[Any, ...]]:
    """Lê a tabela inteira, coluna por coluna, sem `SELECT *`.

    Ordenado por chave: sem `order by`, dois exports do mesmo estado podem gerar
    arquivos binariamente diferentes, e comparar dois Parquets passa a mentir.
    """
    ordem = "sha256" if tabela == "objects" else "id"
    sql = f"select {', '.join(colunas)} from {tabela} order by {ordem}"
    with engine.connect() as conn:
        return [tuple(linha) for linha in conn.execute(text(sql)).fetchall()]


def exportar(
    engine: Engine,
    destino: Path,
    *,
    tabelas: tuple[str, ...] = ("objects", "uploads"),
) -> ResultadoExport:
    """Escreve `objects.parquet` e `uploads.parquet` em `destino`.

    `destino` é criado se não existir. Cada arquivo é escrito num temporário
    ao lado e renomeado: um Parquet pela metade no lugar do bom seria pior que
    não exportar.
    """
    destino.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(database=":memory:")

    mapa = {"objects": COLUNAS_OBJECTS, "uploads": COLUNAS_UPLOADS}
    caminhos: list[Path] = []
    contagem: dict[str, int] = {}

    try:
        for tabela in tabelas:
            colunas = mapa[tabela]
            linhas = _ler_tabela(engine, tabela, colunas)

            final = destino / f"{tabela}.parquet"
            temporario = destino / f".{tabela}.parquet.tmp"

            # `COPY ... TO` do DuckDB escreve Parquet com compressão ZSTD.
            #
            # A tabela é criada a partir das linhas em memória em vez de um
            # `ATTACH` no PostgreSQL: o export roda com a credencial de leitura
            # do catálogo e não precisa que o DuckDB saiba falar Postgres.
            #
            # O schema é declarado com `TIPOS`, não inferido: coluna vazia não
            # tem tipo para inferir, e inferir de dados reais faz o schema do
            # derivado mudar conforme o conteúdo do acervo.
            declaracao = ", ".join(f"{c} {TIPOS[c]}" for c in colunas)
            con.execute(f"create table _t ({declaracao})")
            # Tabela vazia ainda gera Parquet: um arquivo ausente obrigaria o
            # consumidor a tratar "não existe" e "vazio" como casos diferentes.
            if linhas:
                lugar = ", ".join("?" for _ in colunas)
                con.executemany(f"insert into _t values ({lugar})", linhas)

            con.execute(
                f"copy _t to '{temporario}' (format parquet, compression zstd)"
            )
            con.execute("drop table _t")

            temporario.replace(final)
            caminhos.append(final)
            contagem[tabela] = len(linhas)
            log.info("exportado %s: %d linhas -> %s", tabela, len(linhas), final)
    finally:
        con.close()

    return ResultadoExport(
        caminhos=tuple(caminhos),
        linhas_por_tabela=contagem,
        bytes_totais=sum(c.stat().st_size for c in caminhos),
    )


def consultar(caminho: Path, sql: str) -> list[tuple[Any, ...]]:
    """Consulta um Parquet exportado. Existe para o teste provar o arquivo.

    Não é a interface do chat — o chat segue pelo `lake_sql` enquanto o OLTP
    aguentar. Aqui o objetivo é conferir que o derivado é legível e fiel.
    """
    con = duckdb.connect(database=":memory:")
    try:
        consulta = sql.replace("{parquet}", f"read_parquet('{caminho}')")
        return [tuple(linha) for linha in con.execute(consulta).fetchall()]
    finally:
        con.close()
