"""Executor de SQL read-only — o componente crítico da Onda 5.

POR QUE ESTE MÓDULO EXISTE ANTES DO CHAT:

o chat vai gerar SQL a partir de linguagem natural. Um `DROP` gerado por modelo é
o pior cenário possível neste projeto: o dado bruto é o ativo e **não é
reconstruível**. Então o executor é escrito e testado antes de existir qualquer
modelo na frente dele.

QUATRO CAMADAS DE DEFESA, todas independentes:

1. **Allowlist de statement.** Só `SELECT` (e `WITH ... SELECT`) passa. Isso é
   análise sintática da primeira palavra, não procura de substring — procurar
   `"drop"` recusaria `select * from drop_log`.
2. **Statement único.** `SELECT 1; DROP TABLE objects` é recusado por ter dois.
3. **Credencial read-only no banco** (fora deste módulo, no chart). Se as duas
   primeiras falharem, o PostgreSQL recusa a escrita.
3. **`LIMIT` forçado e `statement_timeout`.** Consulta gerada por modelo pode
   varrer tabela inteira; o lake precisa continuar respondendo.

A defesa nº 3 é a única que não depende de mim estar certo — por isso existe
mesmo com a allowlist funcionando.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

log = logging.getLogger(__name__)

#: Teto de linhas devolvidas. Baixo de propósito: o chat responde em texto, não
#: exporta dados. Quem precisa de extração usa o CronJob de Parquet.
LIMITE_PADRAO = 200

#: Tempo máximo de execução, em milissegundos.
TIMEOUT_PADRAO_MS = 5_000

#: Palavras que iniciam um statement aceito. `WITH` cobre CTE que termina em
#: SELECT; `EXPLAIN` fica de fora de propósito — expõe plano e não é resposta.
_PERMITIDOS = ("select", "with")

#: Recusados explicitamente para dar mensagem útil em vez de erro de sintaxe.
#: A allowlist já os barra; esta lista existe só para a mensagem.
_PROIBIDOS = {
    "insert", "update", "delete", "drop", "truncate", "alter", "create",
    "grant", "revoke", "copy", "vacuum", "analyze", "reindex", "cluster",
    "refresh", "call", "do", "set", "reset", "begin", "commit", "rollback",
}

_ESCRITA_EM_CTE = re.compile(r"\b(insert|update|delete|merge)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ResultadoSql:
    """Resposta de uma consulta, pronta para ser mostrada."""

    colunas: list[str]
    linhas: list[tuple[Any, ...]]
    sql_executado: str
    truncado: bool


class SqlRecusado(Exception):
    """O statement não passou na allowlist.

    Tipo próprio para que o chamador distinga "o modelo gerou coisa proibida" de
    "o banco falhou". A primeira é esperada e deve virar mensagem clara ao
    usuário; a segunda é incidente.
    """


def validar(sql: str) -> str:
    """Valida e normaliza o SQL. Levanta `SqlRecusado` se não passar."""
    if not sql or not sql.strip():
        raise SqlRecusado("statement vazio")

    # Remove comentários de linha: um `-- DROP TABLE` não deve ser lido como
    # statement, e um `SELECT 1 -- ; DROP` não deve ser lido como dois.
    sem_comentario = re.sub(r"--[^\n]*", "", sql).strip()

    if not sem_comentario:
        raise SqlRecusado("statement vazio após remover comentários")

    # Statement único: `;` só é aceito no final.
    corpo = sem_comentario.rstrip(";").strip()
    if ";" in corpo:
        raise SqlRecusado(
            "apenas um statement por consulta; múltiplos statements são recusados"
        )

    # Depois de remover `;` sobra string vazia para entrada como ";" ou " ; ;".
    # Sem esta checagem, o `split` abaixo levanta IndexError em vez de recusar.
    if not corpo:
        raise SqlRecusado("statement vazio")

    primeira = corpo.split(maxsplit=1)[0].lower()

    if primeira in _PROIBIDOS:
        raise SqlRecusado(
            f"comando '{primeira}' não é permitido: o executor é read-only"
        )

    if primeira not in _PERMITIDOS:
        raise SqlRecusado(
            f"comando '{primeira}' não é permitido; use SELECT ou WITH"
        )

    # `WITH` pode esconder escrita (`WITH x AS (DELETE ... RETURNING *)`).
    # A allowlist de primeira palavra não alcança isso, então checagem própria.
    if primeira == "with" and _ESCRITA_EM_CTE.search(corpo):
        raise SqlRecusado("WITH contendo escrita é recusado: o executor é read-only")

    return corpo


def _com_limite(sql: str, limite: int) -> str:
    """Garante `LIMIT` sem sobrescrever um explícito.

    Envolver em subselect é mais seguro que concatenar: `select ... limit 10`
    com `limit 200` concatenado viraria sintaxe inválida.

    Pede `limite + 1` linhas de propósito: com exatamente `limite` o banco corta
    e não há como distinguir "havia mais" de "cabia justo". A linha extra é
    descartada depois e serve só como sinal.
    """
    if re.search(r"\blimit\s+\d+\b", sql, flags=re.IGNORECASE):
        return sql
    return f"select * from ({sql}) as _chat_resultado limit {limite + 1}"


def executar(
    engine: Engine,
    sql: str,
    *,
    limite: int = LIMITE_PADRAO,
    timeout_ms: int = TIMEOUT_PADRAO_MS,
) -> ResultadoSql:
    """Valida, executa e devolve o resultado.

    O `statement_timeout` é aplicado na transação, não no `Engine`: um `Engine`
    compartilhado com outros usos não deve carregar configuração de chat.
    """
    validado = validar(sql)
    final = _com_limite(validado, limite)

    with engine.connect() as conn:
        try:
            # `SET LOCAL` vale só para esta transação. Se falhar (dialeto sem
            # suporte), segue — o `LIMIT` já limita o dano.
            conn.execute(text(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))
        except SQLAlchemyError:
            log.warning("statement_timeout não aplicado neste dialeto")

        resultado = conn.execute(text(final))
        colunas = list(resultado.keys())
        linhas = resultado.fetchall()

    # A linha extra (pedida em `_com_limite`) é o sinal de truncagem: se veio,
    # havia mais. Cortar antes de devolver evita expor a linha sentinela.
    truncado = len(linhas) > limite
    if truncado:
        linhas = linhas[:limite]

    return ResultadoSql(
        colunas=colunas,
        linhas=[tuple(linha) for linha in linhas],
        sql_executado=final,
        truncado=truncado,
    )
