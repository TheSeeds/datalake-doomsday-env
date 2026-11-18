"""Sinal de frescor: o que o lake sabe sobre a própria saúde.

POR QUE ESTE MÓDULO EXISTE ANTES DE QUALQUER PAINEL:

em 2026-11-18 o backup falhou em 100% das execuções por horas. A informação
estava em `kubectl get jobs`, visível, e ninguém olhou. Métrica nenhuma teria
resolvido isso: o que faltava era alguém perguntando. O que este módulo faz é
tornar a pergunta respondível em uma chamada, e do jeito certo.

A DECISÃO QUE O MÓDULO INTEIRO GIRA EM TORNO:

**sinal ausente é FALHA, não OK.** Um lake novo, com o backup nunca executado,
tem `ultimo_sucesso = NULL`. A resposta confortável é "não há problema
registrado"; a resposta correta é "isto nunca funcionou". A diferença entre as
duas é a diferença entre o incidente de ontem e a detecção dele.

Por isso `estado()` devolve `desconhecido` para sinal que nunca registrou nada,
e `desconhecido` conta como problema em `resumo()`.

LIMIARES EXPLÍCITOS, E O QUE ELES NÃO SÃO:

backup é diário, então 36 h de silêncio significa uma execução perdida (não
duas). Ingestão por `drop/` roda a cada 5 minutos, mas pode não haver arquivo
para ingerir — daí o limiar folgado. Estes números são política, não física:
mudá-los é decisão, e por isso estão aqui em cima, nomeados.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import text
from sqlalchemy.engine import Engine

log = logging.getLogger(__name__)

#: Idade máxima tolerada antes de o sinal ser considerado velho.
#: backup: diário às 03:00 → 36 h cobre uma execução perdida sem alarmar falso.
#: ingestao: CronJob de 5 min, mas sem arquivo não há o que ingerir.
LIMIARES = {
    "backup": timedelta(days=1, hours=12),
    "ingestao": timedelta(days=2),
    "export": timedelta(days=8),
}

#: Sem limiar declarado, o sinal é tratado como desconhecido — nunca como OK.
LIMIAR_PADRAO = timedelta(days=2)

Estado = Literal["saudavel", "velho", "falhou", "desconhecido"]


@dataclass(frozen=True, slots=True)
class Sinal:
    """Retrato de um sinal de saúde."""

    sinal: str
    estado: Estado
    ultimo_sucesso: datetime | None
    ultima_falha: datetime | None
    detalhe: str | None
    idade: timedelta | None

    def texto(self) -> str:
        """Uma linha legível. É o que aparece no `lake_estado`."""
        partes = [f"{self.sinal}: {self.estado}"]
        if self.ultimo_sucesso:
            partes.append(f"último sucesso há {_humanizar(self.idade)}")
        else:
            partes.append("nenhum sucesso registrado")
        if self.ultima_falha and self.estado in ("falhou", "velho"):
            partes.append(f"última falha {self.ultima_falha.isoformat()}")
        if self.detalhe:
            partes.append(f"({self.detalhe})")
        return "  ".join(partes)


def _humanizar(idade: timedelta | None) -> str:
    if idade is None:
        return "?"
    segundos = int(idade.total_seconds())
    if segundos < 90:
        return f"{segundos}s"
    minutos = segundos // 60
    if minutos < 90:
        return f"{minutos}min"
    horas = minutos // 60
    if horas < 48:
        return f"{horas}h"
    return f"{horas // 24}d"


def _como_datetime(valor: object) -> datetime | None:
    """Normaliza o instante lido do banco.

    SQLite devolve `timestamp` como texto; PostgreSQL devolve `datetime`. Sem
    normalizar, a subtração `agora - sucesso` levanta `TypeError` num dialeto e
    funciona no outro — o mesmo padrão que já apareceu em `text()` devolvendo
    JSON como string em SQLite. Converter na borda é mais barato que manter
    duas cópias da lógica.
    """
    if valor is None or isinstance(valor, datetime):
        return valor
    if isinstance(valor, str):
        # PostgreSQL grava com offset; SQLite grava "YYYY-MM-DD HH:MM:SS".
        texto_limpo = valor.replace("Z", "+00:00")
        try:
            devolvido = datetime.fromisoformat(texto_limpo)
        except ValueError:
            log.warning("instante ilegível em saude: %r", valor)
            return None
        # Sem timezone, assume UTC: é o que a coluna guarda em produção.
        return devolvido if devolvido.tzinfo else devolvido.replace(tzinfo=UTC)
    log.warning("tipo inesperado em saude: %r", type(valor))
    return None


def registrar(
    engine: Engine,
    sinal: str,
    *,
    sucesso: bool,
    detalhe: str | None = None,
    quando: datetime | None = None,
) -> None:
    """Grava o resultado de uma execução de rotina.

    `upsert` porque a primeira execução de uma rotina nova cria a linha; as
    seguintes atualizam. Sem isso, o primeiro backup bem-sucedido de um lake
    ficaria sem registro até alguém criar a linha à mão.
    """
    momento = quando or datetime.now(UTC)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                insert into saude (sinal, ultimo_sucesso, ultima_falha,
                                   total_ok, total_falha, detalhe, atualizado_em)
                values (:sinal,
                        case when :ok then :quando else null end,
                        case when :ok then null else :quando end,
                        case when :ok then 1 else 0 end,
                        case when :ok then 0 else 1 end,
                        :detalhe, :quando)
                on conflict (sinal) do update set
                    ultimo_sucesso = case when :ok
                        then excluded.ultimo_sucesso else saude.ultimo_sucesso end,
                    ultima_falha = case when :ok
                        then saude.ultima_falha else excluded.ultima_falha end,
                    total_ok = saude.total_ok + excluded.total_ok,
                    total_falha = saude.total_falha + excluded.total_falha,
                    detalhe = excluded.detalhe,
                    atualizado_em = excluded.atualizado_em
                """
            ),
            {"sinal": sinal, "ok": sucesso, "quando": momento, "detalhe": detalhe},
        )


def estado(engine: Engine, sinais: tuple[str, ...] | None = None) -> list[Sinal]:
    """Estado atual de cada sinal conhecido, mais os pedidos que não existem.

    Sinais pedidos e ausentes voltam como `desconhecido`: quem pergunta "e o
    backup?" precisa de uma resposta, não de silêncio.
    """
    agora = datetime.now(UTC)
    with engine.connect() as conn:
        linhas = conn.execute(
            text(
                "select sinal, ultimo_sucesso, ultima_falha, detalhe "
                "from saude order by sinal"
            )
        ).fetchall()

    registrados = {linha[0]: linha for linha in linhas}
    pedidos = sinais or tuple(registrados)

    resultado: list[Sinal] = []
    for nome in pedidos:
        linha = registrados.get(nome)
        if linha is None:
            resultado.append(
                Sinal(
                    sinal=nome,
                    estado="desconhecido",
                    ultimo_sucesso=None,
                    ultima_falha=None,
                    detalhe="nunca registrou nada: isto não é o mesmo que estar ok",
                    idade=None,
                )
            )
            continue

        _, sucesso_bruto, falha_bruta, detalhe = linha
        sucesso = _como_datetime(sucesso_bruto)
        falha = _como_datetime(falha_bruta)
        idade = agora - sucesso if sucesso else None
        limiar = LIMIARES.get(nome, LIMIAR_PADRAO)

        if sucesso is None:
            # Nunca funcionou. Não é "sem problema": é o pior estado possível,
            # e é exatamente o que o incidente de 2026-11-18 parecia ser.
            estado_final: Estado = "falhou" if falha else "desconhecido"
        elif idade is not None and idade > limiar:
            estado_final = "velho"
        elif falha is not None and sucesso is not None and falha > sucesso:
            # Falhou depois do último sucesso: a rotina está quebrada agora,
            # mesmo que o último sucesso esteja dentro do limiar.
            estado_final = "falhou"
        else:
            estado_final = "saudavel"

        resultado.append(
            Sinal(
                sinal=nome,
                estado=estado_final,
                ultimo_sucesso=sucesso,
                ultima_falha=falha,
                detalhe=detalhe,
                idade=idade,
            )
        )

    # Sinais registrados e não pedidos não entram: quem pediu uma lista quer
    # aquela lista, não o catálogo inteiro de sinais.
    return resultado


def resumo(engine: Engine) -> tuple[bool, list[Sinal]]:
    """`(tudo_ok, sinais)`. O booleano é o que `/health` devolve com 503."""
    sinais = estado(engine)
    # `all()` de lista vazia é `True`. Sem o `and sinais`, um lake que nunca
    # registrou nada passaria como saudável — exatamente o falso positivo que
    # este módulo existe para impedir. Um lake sem sinal não é saudável: é um
    # lake sobre o qual nada se sabe.
    tudo_ok = bool(sinais) and all(s.estado == "saudavel" for s in sinais)
    return tudo_ok, sinais
