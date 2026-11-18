"""Tipos do núcleo de domínio.

`Record` é o que o catálogo guarda. `ObjectRef` é onde o byte mora. Separar os
dois é o que permite trocar Garage por outro S3 sem tocar no catálogo, e é o que
torna `derived/` descartável: o `Record` descreve o objeto bruto, não a cópia
analítica.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class UploadState(StrEnum):
    """Máquina de estados única para toda porta de entrada.

    received → hashed → stored → cataloged → processing → done
                                                 ↘ failed
    """

    RECEIVED = "received"
    HASHED = "hashed"
    STORED = "stored"
    CATALOGED = "cataloged"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ObjectRef:
    """Localização de um objeto no storage bruto.

    `key` é sempre o layout determinístico de `lakecore.layout.raw_key`; o
    `sha256` aparece no caminho, o que faz a escrita ser idempotente por
    construção: duas ingestões do mesmo conteúdo disputam a mesma chave.
    """

    bucket: str
    key: str
    sha256: str
    size: int
    content_type: str


@dataclass(frozen=True, slots=True)
class Record:
    """Linha do catálogo.

    `metadados` é livre de propósito: o lake aceita dado heterogêneo e não impõe
    schema rígido na entrada. O que é fixo são proveniência e integridade —
    `origem`, `sha256`, `coletado_em`.
    """

    sha256: str
    bucket: str
    key: str
    size: int
    content_type: str
    origem: str
    tipo: str
    coletado_em: datetime
    metadados: dict[str, Any] = field(default_factory=dict)
    state: UploadState = UploadState.CATALOGED


@dataclass(frozen=True, slots=True)
class IngestRequest:
    """Pedido de ingestão de um arquivo local.

    `origem` é obrigatória: sem proveniência o dado é órfão, e um lake sem
    procedência é um repositório de arquivos.
    """

    path: str
    origem: str
    tipo: str | None = None
    metadados: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class UploadBatch:
    """Agregação de uma leva de ingestão (um `drop/`, um POST, um push)."""

    id: str
    origem: str
    total: int
    aceitos: int
    duplicados: int
    falhas: int
