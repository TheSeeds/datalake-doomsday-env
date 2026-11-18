"""Ingestão: o coração do domínio.

`ingest()` recebe um caminho local e devolve um `Record` catalogado. Idempotente
por `sha256`: ingerir o mesmo conteúdo duas vezes produz **um** objeto e **uma**
linha.

Regras que esta implementação precisa sustentar:

1. **Idempotência por conteúdo**, não por nome de arquivo. Renomear não duplica.
2. **Fail-closed na integridade**: se o hash calculado divergir do verificado
   após a escrita, o registro não é catalogado.
3. **Proveniência obrigatória**: sem `origem`, o dado é órfão.
4. **Sem I/O além do necessário**: lê o arquivo uma vez, em streaming, sem
   carregar o conteúdo inteiro em memória — um lake recebe arquivo grande.

A ordem das operações é deliberada: escreve no storage **antes** de catalogar.
O inverso produziria linha no catálogo apontando para objeto inexistente, e o
catálogo é a única fonte de verdade sobre o que existe.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lakecore.errors import (
    DuplicateObjectError,
    IntegrityMismatchError,
    UnsupportedObjectError,
)
from lakecore.layout import raw_key
from lakecore.models import IngestRequest, ObjectRef, Record
from lakecore.ports import Catalog, Clock, ObjectStore

#: Tamanho do bloco de leitura. 1 MiB equilibra syscalls e memória; o arquivo
#: nunca é carregado inteiro.
_BLOCO = 1 << 20

#: Acima disto o arquivo é rejeitado por padrão. É um limite de segurança, não de
#: produto: pode ser sobrescrito pelo chamador sem alterar o domínio.
TAMANHO_MAXIMO_PADRAO = 8 << 30  # 8 GiB

_MIME_POR_EXTENSAO: dict[str, str] = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".json": "application/json",
    ".xml": "application/xml",
    ".html": "text/html",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".zip": "application/zip",
    ".gz": "application/gzip",
    ".log": "text/plain",
}

_MIME_PADRAO = "application/octet-stream"


@dataclass(frozen=True, slots=True)
class IngestResult:
    """Resultado da ingestão.

    `record` é sempre preenchido quando não há exceção — inclusive no caso de
    duplicado, onde aponta para o registro que **já existia**. Isso permite ao
    chamador tratar duplicata como sucesso sem perder a referência.
    """

    record: Record
    duplicate: bool


def hash_file(path: Path, *, bloco: int = _BLOCO) -> tuple[str, int]:
    """Calcula `sha256` e tamanho em streaming.

    Devolve `(sha256_hex, bytes_lidos)`. O tamanho é contado aqui, não lido de
    `stat()`, porque entre o `stat` e a leitura o arquivo pode mudar — e um
    tamanho inconsistente com o hash é dado errado no catálogo.
    """
    digest = hashlib.sha256()
    total = 0

    with path.open("rb") as handle:
        while chunk := handle.read(bloco):
            digest.update(chunk)
            total += len(chunk)

    return digest.hexdigest(), total


def classify(path: Path) -> tuple[str, str]:
    """Deriva `(tipo, content_type)` do nome.

    `tipo` é a classificação grosseira usada no layout (`pdf`, `texto`, `binario`);
    `content_type` é o MIME. Ambos são derivados de extensão — quando o chamador
    souber melhor, ele sobrescreve via `IngestRequest.tipo`.
    """
    extensao = path.suffix.lower()
    content_type = _MIME_POR_EXTENSAO.get(extensao, _MIME_PADRAO)

    if content_type.startswith("text/"):
        tipo = "texto"
    elif content_type.startswith("image/"):
        tipo = "imagem"
    elif extensao:
        tipo = extensao.lstrip(".")
    else:
        tipo = "binario"

    return tipo, content_type


def ingest(
    request: IngestRequest,
    *,
    store: ObjectStore,
    catalog: Catalog,
    clock: Clock,
    tamanho_maximo: int = TAMANHO_MAXIMO_PADRAO,
) -> IngestResult:
    """Ingere um arquivo local, idempotente por `sha256`.

    Levanta `UnsupportedObjectError` para arquivo ausente, diretório ou acima do
    limite; `IntegrityMismatchError` quando o objeto gravado não confere;
    `DuplicateObjectError` **nunca** escapa daqui — é convertida em
    `IngestResult(duplicate=True)`.
    """
    if not request.origem.strip():
        raise UnsupportedObjectError("origem é obrigatória: dado sem proveniência é órfão")

    path = Path(request.path)

    if path.is_dir():
        raise UnsupportedObjectError(f"diretório não é ingerível: {path}")
    if not path.is_file():
        raise UnsupportedObjectError(f"arquivo não encontrado: {path}")

    if path.stat().st_size > tamanho_maximo:
        raise UnsupportedObjectError(
            f"arquivo acima do limite ({path.stat().st_size} > {tamanho_maximo}): {path}"
        )

    sha256, size = hash_file(path)
    tipo_derivado, content_type = classify(path)
    tipo = request.tipo or tipo_derivado
    coletado_em = clock.now()

    chave = raw_key(
        origem=request.origem,
        tipo=tipo,
        coletado_em=coletado_em,
        sha256=sha256,
    )

    ja_existente = catalog.by_sha256(sha256)
    if ja_existente is not None:
        return IngestResult(record=ja_existente, duplicate=True)

    ref = ObjectRef(
        bucket="raw",
        key=chave,
        sha256=sha256,
        size=size,
        content_type=content_type,
    )

    _gravar_verificando(store=store, ref=ref, path=path, sha256=sha256)

    record = Record(
        sha256=sha256,
        bucket="raw",
        key=chave,
        size=size,
        content_type=content_type,
        origem=request.origem,
        tipo=tipo,
        coletado_em=coletado_em,
        metadados=_metadados(path=path, request=request),
    )

    try:
        catalog.add(record)
    except DuplicateObjectError:
        # Corrida entre dois ingestores do mesmo conteúdo: o storage já foi
        # escrito de forma idempotente (mesma chave), então o resultado correto
        # é o registro do vencedor, não um erro.
        existente = catalog.by_sha256(sha256)
        if existente is None:
            raise
        return IngestResult(record=existente, duplicate=True)

    return IngestResult(record=record, duplicate=False)


def _gravar_verificando(
    *, store: ObjectStore, ref: ObjectRef, path: Path, sha256: str
) -> None:
    """Grava o objeto. **Não** pergunta ao storage se ele já existe.

    ADR-013: `exists()` no storage é proibido no caminho de ingestão, por dois
    motivos independentes:

    1. **A chave de `ingest` é write-only** (ADR-011). `HeadObject` com essa
       chave responde 403, e 403 significa "não posso ver" — não "não existe".
       Tratar 403 como ausência era mentira: foi o que derrubou a primeira
       ingestão real com HTTP 500.
    2. **Não é necessário.** A chave é `sha256` do conteúdo: escrever de novo o
       mesmo dado grava sobre a mesma chave, com os mesmos bytes. Idempotência
       vem do endereçamento, não de uma checagem.

    Quem responde "já existe?" é o **catálogo**, que tem o índice único em
    `sha256` e é consultado antes desta função. O storage é o último a saber.

    A verificação de integridade do conteúdo é feita relendo o storage no
    `restore drill` (Onda 6), com credencial que tem leitura.
    """
    with path.open("rb") as handle:
        dados = handle.read()

    # Confere o que vai ser gravado contra o hash já calculado: protege contra
    # arquivo modificado entre `hash_file` e a escrita.
    if hashlib.sha256(dados).hexdigest() != sha256:
        raise IntegrityMismatchError(
            f"arquivo mudou entre o hash e a escrita: {path}"
        )

    store.put(ref, dados)


def _metadados(*, path: Path, request: IngestRequest) -> dict[str, Any]:
    """Metadados mínimos de proveniência.

    O nome original é preservado porque o `key` no storage é um hash — sem isto,
    não haveria como saber de que arquivo veio.
    """
    metadados: dict[str, Any] = {
        "nome_original": path.name,
        "extensao": path.suffix.lower(),
    }
    metadados.update(request.metadados)
    return metadados
