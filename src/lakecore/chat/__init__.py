"""Chat: conversar com os próprios dados.

O chat não "sabe" nada do acervo por conta própria. Toda afirmação sobre os dados
nasce de uma consulta executada contra o catálogo. O modelo redige; o banco
responde.
"""

from __future__ import annotations

from lakecore.chat.executor import (
    LIMITE_PADRAO,
    TIMEOUT_PADRAO_MS,
    ResultadoSql,
    SqlRecusado,
    executar,
    validar,
)

__all__ = [
    "LIMITE_PADRAO",
    "TIMEOUT_PADRAO_MS",
    "ResultadoSql",
    "SqlRecusado",
    "executar",
    "validar",
]
