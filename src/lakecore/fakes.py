"""Fakes em memória das portas.

Existem para que os testes de `lakecore` rodem em milissegundos, sem container e
sem rede — requisito das ondas 0–2. Não são mocks de framework: são
implementações reais (e corretas) das portas, só que sem persistência.

Um fake que não respeita o contrato é pior que nenhum teste: produz confiança
falsa. Por isso o `FakeCatalog` levanta `DuplicateObjectError` de verdade e o
`FakeObjectStore` guarda bytes de verdade.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from lakecore.errors import DuplicateObjectError
from lakecore.models import ObjectRef, Record


@dataclass
class FakeObjectStore:
    """Storage em memória, com contagem de escritas para provar idempotência."""

    objetos: dict[tuple[str, str], bytes] = field(default_factory=dict)
    escritas: int = 0

    def put(self, ref: ObjectRef, data: bytes) -> None:
        self.escritas += 1
        self.objetos[(ref.bucket, ref.key)] = data

    def exists(self, bucket: str, key: str) -> bool:
        """Presença no fake.

        A ingestão **não** chama isto (ADR-013); existe para testes que querem
        afirmar o efeito da escrita. O fake tem leitura porque é memória, não
        storage com política — o que ele não pode fazer é dar a impressão de que
        a ingestão depende desta checagem.
        """
        return (bucket, key) in self.objetos


@dataclass
class FakeCatalog:
    """Catálogo em memória, idempotente por `sha256` como o contrato exige."""

    registros: dict[str, Record] = field(default_factory=dict)
    insercoes: int = 0

    def add(self, record: Record) -> None:
        if record.sha256 in self.registros:
            raise DuplicateObjectError(record.sha256)
        self.insercoes += 1
        self.registros[record.sha256] = record

    def by_sha256(self, sha256: str) -> Record | None:
        return self.registros.get(sha256)


@dataclass
class FixedClock:
    """Relógio determinístico.

    `coletado_em` entra no catálogo e no layout do storage; um teste que depende
    do relógio real não é reproduzível nem de segunda-feira.
    """

    momento: datetime = field(default_factory=lambda: datetime(2026, 11, 18, 12, 0, tzinfo=UTC))

    def now(self) -> datetime:
        return self.momento
