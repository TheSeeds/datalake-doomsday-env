"""Portas (interfaces) do núcleo de domínio.

O núcleo declara o que precisa; a infraestrutura decide como cumprir. As
implementações reais (Garage, PostgreSQL) chegam nas ondas 2 e 3. Até lá, os
testes usam fakes em memória — o que mantém `make test` na casa dos milissegundos
e sem container.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from lakecore.models import ObjectRef, Record


@runtime_checkable
class ObjectStore(Protocol):
    """Escrita e leitura de bytes no storage bruto.

    O papel `ingest` da arquitetura tem permissão **write-only** no prefixo
    `raw/`. Por isso `put` é obrigatório na porta e `get` é opcional: um
    ingestor não deve poder ler o acervo que ajudou a gravar.

    **`exists` não faz parte do contrato** (ADR-013). Perguntar "o objeto já
    está lá?" a um storage write-only recebe 403, e 403 não distingue "não
    existe" de "não posso ver" — responder qualquer coisa seria mentir. Quem
    sabe o que já foi ingerido é o **catálogo**, pelo `sha256`.

    Implementações **podem** oferecer `exists` (útil para verificação com
    credencial de leitura e para o `restore drill`), mas a ingestão não a usa.
    """

    def put(self, ref: ObjectRef, data: bytes) -> None: ...


@runtime_checkable
class Catalog(Protocol):
    """Persistência de metadados.

    `add` deve ser idempotente por `sha256`: segunda inserção do mesmo hash
    levanta `DuplicateObjectError` em vez de duplicar a linha. Essa é a garantia
    que faz "rodar duas vezes" ser seguro — requisito da Onda 4.
    """

    def add(self, record: Record) -> None: ...

    def by_sha256(self, sha256: str) -> Record | None: ...


@runtime_checkable
class Clock(Protocol):
    """Tempo injetável.

    `coletado_em` entra no catálogo e é usado por retenção. Nos testes ele é
    fixo: saída dependente de relógio real não é reproduzível.
    """

    def now(self) -> datetime: ...
