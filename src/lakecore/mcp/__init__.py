"""Servidor MCP — a ponte entre a tela de chat e o catálogo.

POR QUE MCP E NÃO UMA API PRÓPRIA:

a tela (Hermes Agent) é um *runtime de agente*: ela já sabe dirigir ferramentas,
manter memória e conversar em linguagem natural. Reescrever isso seria refazer o
que existe. MCP é o contrato padrão para "expor ferramentas a um agente", então
a tela **não vira dona do lake**: ela é cliente. Derrubar o Hermes não derruba a
ingestão, o backup nem o catálogo.

O QUE O MODELO NÃO PODE FAZER AQUI:

nenhuma ferramenta escreve. `lake_sql` reusa o executor da 5.1 (allowlist +
statement único + `WITH`-com-escrita recusado + `LIMIT`/`timeout`), e a conexão
usa a credencial read-only do banco. As três defesas de parsing poderiam estar
erradas ao mesmo tempo e o PostgreSQL ainda recusaria a escrita.

O SQL EXECUTADO É DEVOLVIDO SEMPRE. É o que separa "conversar com os dados" de
"confiar no chatbot": a pessoa vê a consulta e pode contestá-la.

QUATRO FERRAMENTAS, e não três:

`lake_esquema` existe porque foi medido (2026-11-18) que modelo barato inventa
nome de coluna — perguntas sobre coluna inexistente fizeram 1 de 4 modelos
devolver string vazia em vez de admitir. Uma ferramenta que entrega o schema
real, chamada antes de gerar SQL, ataca a causa em vez do sintoma.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from mcp.server.fastmcp import FastMCP
from sqlalchemy import CheckConstraint, create_engine, text
from sqlalchemy.engine import Engine

from lakecore.chat.executor import (
    LIMITE_PADRAO,
    TIMEOUT_PADRAO_MS,
    ResultadoSql,
    SqlRecusado,
    aplicar_timeout,
    executar,
)
from lakecore.db.models import Base

log = logging.getLogger(__name__)

#: Nome do servidor no registro MCP. É o prefixo que a tela mostra.
NOME = "lake"

#: Teto da busca por filtro. Menor que o do SQL porque a busca devolve *linhas de
#: objeto* (com sha256), que são largas — 50 já é mais do que cabe na tela.
LIMITE_BUSCA = 50

#: Tabelas que a tela pode ver. Fora daqui não há ferramenta — o modelo não
#: descobre tabela nova por acaso.
TABELAS = ("objects", "uploads")

mcp: FastMCP = FastMCP(NOME)

#: `Engine` é criado uma vez por processo. O MCP roda como stdio, um processo por
#: sessão de tela, então não há risco de pool compartilhado entre inquilinos.
_engine: Engine | None = None


def _url_do_banco() -> str:
    """URL do catálogo, vinda do ambiente.

    Recusa explícita em vez de chutar um default: um MCP que conecta no banco
    "errado" e responde com dados de outro lake é pior que um MCP que não sobe.
    """
    url = os.environ.get("LAKECORE_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "LAKECORE_DATABASE_URL não definida: o servidor MCP precisa saber "
            "qual catálogo servir. Aponte para a credencial READ-ONLY."
        )
    return url


def engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(_url_do_banco(), pool_pre_ping=True, future=True)
    return _engine


def _tipar(valor: Any) -> Any:
    """Converte tipos do driver em algo que vira JSON no transporte MCP.

    `Decimal` e `datetime` não são serializáveis direto. Converter aqui, no
    limite, é o que evita o erro aparecer como "falha do modelo" na tela.
    """
    if isinstance(valor, Decimal):
        return int(valor) if valor == valor.to_integral_value() else float(valor)
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if isinstance(valor, (bytes, memoryview)):
        return f"<{len(bytes(valor))} bytes>"
    return valor


def formatar(resultado: ResultadoSql) -> str:
    """Texto legível com o SQL à vista.

    O SQL vem **antes** dos dados de propósito: se a consulta estiver errada, a
    pessoa percebe pelo SQL, não pelo número — o número errado parece certo.
    """
    linhas = [
        "SQL executado:",
        resultado.sql_executado,
        "",
        "Colunas: " + ", ".join(resultado.colunas),
        f"Linhas: {len(resultado.linhas)}",
        "",
    ]
    for linha in resultado.linhas:
        linhas.append(" | ".join(str(_tipar(v)) for v in linha))
    if resultado.truncado:
        linhas.append("")
        linhas.append(
            f"(resultado truncado: havia mais de {LIMITE_PADRAO} linhas; "
            "refine a consulta ou use agregação)"
        )
    if not resultado.linhas:
        linhas.append("(nenhuma linha: a consulta é válida, mas não casou com nada)")
    return "\n".join(linhas)


def _status_permitidos() -> str:
    """Lê os valores do CHECK do próprio modelo.

    Copiar a lista aqui criaria uma segunda fonte de verdade que envelhece em
    silêncio: no dia em que o schema ganhar um estado novo, a tela continuaria
    dizendo que ele não existe.
    """
    for restricao in Base.metadata.tables["objects"].constraints:
        # O nome chega prefixado pela convenção de metadata (`ck_objects_...`);
        # comparar o sufixo evita repetir o nome da tabela aqui.
        if (
            isinstance(restricao, CheckConstraint)
            and (restricao.name or "").endswith("status_valido")
        ):
            valores = re.findall(r"'([a-z]+)'", str(restricao.sqltext))
            return ", ".join(valores)
    return "(não declarado no modelo)"


@mcp.tool()
def lake_esquema() -> str:
    """Devolve o schema do catálogo: tabelas, colunas e estados válidos.

    Chame antes de escrever SQL. O catálogo usa nomes em português sem acento
    (`origem`, `tipo`, `coletado_em`); inventar nome de coluna produz consulta
    inválida ou, pior, consulta válida que responde outra pergunta.
    """
    partes = ["Catálogo do lake. Apenas SELECT é permitido.", ""]

    for nome in TABELAS:
        tabela = Base.metadata.tables[nome]
        partes.append(f"{nome}:")
        for coluna in tabela.columns:
            tipo = coluna.type.compile(engine().dialect)
            nulo = "" if coluna.nullable else " NOT NULL"
            partes.append(f"  {coluna.name} {tipo}{nulo}")
        partes.append("")

    partes.extend([
        f"Valores permitidos em objects.status: {_status_permitidos()}",
        "",
        "objects.metadados é JSON (aceita operadores de JSON: ->, ->>, @>).",
        "objects.origem é a PROCEDÊNCIA (de onde veio: whatsapp, email, dropbox…);",
        "objects.tipo é a NATUREZA do arquivo (texto, foto, pdf…). Não confunda.",
    ])
    return "\n".join(partes)


@mcp.tool()
def lake_buscar(
    origem: str | None = None,
    tipo: str | None = None,
    status: str | None = None,
    desde: str | None = None,
    ate: str | None = None,
    limite: int = LIMITE_BUSCA,
) -> str:
    """Busca objetos do acervo por filtro, sem gerar SQL.

    Caminho determinístico: funciona igual com ou sem modelo de linguagem, e é o
    que atende "pergunta por filtro" quando não há LLM disponível. Datas em
    `AAAA-MM-DD` (inclusive nas duas pontas).
    """
    condicoes: list[str] = []
    params: dict[str, Any] = {}

    if origem:
        condicoes.append("origem = :origem")
        params["origem"] = origem
    if tipo:
        condicoes.append("tipo = :tipo")
        params["tipo"] = tipo
    if status:
        condicoes.append("status = :status")
        params["status"] = status
    if desde:
        condicoes.append("coletado_em >= :desde")
        params["desde"] = desde
    if ate:
        # O limite superior é o dia seguinte, calculado aqui em vez de no SQL:
        # `::date + 1` é exclusivo do PostgreSQL e faria a ferramenta funcionar
        # num dialeto e falhar no outro. Data inválida vira erro na conversão,
        # que é o comportamento desejado — melhor recusar que filtrar errado.
        condicoes.append("coletado_em < :ate_fim")
        params["ate_fim"] = (date.fromisoformat(ate) + timedelta(days=1)).isoformat()

    onde = f"where {' and '.join(condicoes)}" if condicoes else ""
    limite_efetivo = max(1, min(int(limite), LIMITE_BUSCA))
    # Busca N+1 para distinguir "cabia justo" de "havia mais" — a mesma lição
    # do executor, que devolve a linha sentinela e a descarta.
    sql = (
        "select sha256, origem, tipo, size_bytes, content_type, status, coletado_em "
        f"from objects {onde} order by coletado_em desc limit {limite_efetivo + 1}"
    )

    with engine().connect() as conn:
        aplicar_timeout(conn, TIMEOUT_PADRAO_MS)
        linhas = conn.execute(text(sql), params).fetchall()

    havia_mais = len(linhas) > limite_efetivo
    linhas = linhas[:limite_efetivo]

    if not linhas:
        return (
            "SQL executado:\n"
            + sql
            + "\n\n(nenhum objeto casou com esse filtro; o acervo pode estar vazio "
            "ou o filtro restritivo demais)"
        )

    saida = ["SQL executado:", sql, "", f"Objetos: {len(linhas)}", ""]
    for sha, orig, tp, tam, ct, st, quando in linhas:
        saida.append(
            f"{sha[:12]}…  {_tipar(quando)}  {orig}/{tp}  "
            f"{_tipar(tam)}B  {ct}  {st}"
        )
    if havia_mais:
        saida.append("")
        saida.append("(havia mais objetos que o limite; refine o filtro)")
    return "\n".join(saida)


@mcp.tool()
def lake_sql(sql: str) -> str:
    """Executa um SELECT no catálogo e devolve as linhas junto com o SQL.

    Só `SELECT` (e `WITH ... SELECT`) passa; escritas são recusadas antes de
    tocar no banco. O resultado vem limitado e a consulta tem tempo máximo de
    execução. Se a pergunta não puder ser respondida com as colunas de
    `lake_esquema`, diga isso à pessoa em vez de inventar coluna.
    """
    try:
        resultado = executar(engine(), sql)
    except SqlRecusado as e:
        return (
            f"Consulta recusada: {e}\n\n"
            "O acesso ao catálogo é read-only. Reformule a pergunta como leitura "
            "de dados (SELECT)."
        )
    except Exception as e:  # noqa: BLE001
        # Erro do banco é incidente, mas a tela precisa de causa legível: o
        # modelo conserta sintaxe a partir da mensagem; sem ela, ele chuta.
        log.warning("falha ao executar SQL do chat: %s", e)
        return (
            f"A consulta falhou: {type(e).__name__}: {str(e).splitlines()[0]}\n\n"
            "Verifique nomes de tabela e coluna em lake_esquema e tente de novo."
        )
    return formatar(resultado)


@mcp.tool()
def lake_estado() -> str:
    """Resumo de saúde do lake: volume, origens, últimos lotes e o que falhou.

    É diagnóstico, não exploração. Serve para a pessoa saber se o acervo está de
    pé antes de confiar numa resposta.
    """
    consultas = {
        "objetos no catálogo": "select count(*) from objects",
        "bytes catalogados": "select coalesce(sum(size_bytes), 0) from objects",
        "objetos por status": (
            "select status, count(*) from objects group by status order by 2 desc"
        ),
        "objetos por origem": (
            "select origem, count(*) from objects group by origem order by 2 desc limit 10"
        ),
        "últimos lotes de ingestão": (
            "select origem, total, aceitos, duplicados, falhas, iniciado_em "
            "from uploads order by iniciado_em desc limit 5"
        ),
    }

    partes = ["Estado do lake", ""]
    with engine().connect() as conn:
        aplicar_timeout(conn, TIMEOUT_PADRAO_MS)
        for rotulo, sql in consultas.items():
            linhas = conn.execute(text(sql)).fetchall()
            if len(linhas) == 1 and len(linhas[0]) == 1:
                partes.append(f"{rotulo}: {_tipar(linhas[0][0])}")
                continue
            partes.append(f"{rotulo}:")
            for linha in linhas:
                partes.append("  " + " | ".join(str(_tipar(v)) for v in linha))
            if not linhas:
                partes.append("  (vazio)")
            partes.append("")
    return "\n".join(partes)


def main() -> None:
    """Ponto de entrada: transporte stdio, o que a tela espera de um subprocesso."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    mcp.run()


if __name__ == "__main__":
    main()
