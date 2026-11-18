"""Erros do núcleo de domínio.

Erros existem para que a falha seja tipada no limite do sistema, não engolida.
A lição do geoflow está registrada em `docs/decisoes.md`: um `except` que devolve
`[]` faz o painel mentir sobre a saúde da fonte.
"""

from __future__ import annotations


class IngestError(Exception):
    """Falha ao ingerir. Base para os casos abaixo."""


class UnsupportedObjectError(IngestError):
    """O item não pode ser ingerido (tipo, tamanho ou forma inválida)."""


class IntegrityMismatchError(IngestError):
    """O hash calculado não corresponde ao esperado."""


class StorageUnavailableError(IngestError):
    """O storage recusou a operação por motivo que não é de conteúdo.

    Existe para separar "não consegui escrever" de "escrevi e o conteúdo não
    confere". Sem essa distinção, uma falha de credencial aparece como erro de
    integridade e manda a investigação para o lugar errado.
    """


class DuplicateObjectError(IngestError):
    """O `sha256` já está no catálogo.

    Ingestion é idempotente por hash, então este erro é **esperado** na
    reprocessagem e costuma ser tratado como sucesso pelo chamador. Ele existe
    como tipo próprio para que a distinção entre "já existia" e "falhou" não
    dependa de comparar strings de mensagem.
    """

    def __init__(self, sha256: str) -> None:
        self.sha256 = sha256
        super().__init__(f"objeto já catalogado: sha256={sha256}")
