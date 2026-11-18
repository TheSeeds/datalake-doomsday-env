"""Testes do contrato de tipos.

Não testam comportamento — testam que o contrato continua honesto. Se alguém
tornar `Record` mutável, ou transformar `DuplicateObjectError` em erro genérico,
estes testes falham antes de o problema aparecer na Onda 4.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from lakecore import (
    Catalog,
    Clock,
    DuplicateObjectError,
    IngestError,
    IntegrityMismatchError,
    ObjectRef,
    ObjectStore,
    Record,
    UnsupportedObjectError,
    UploadState,
)


def test_record_e_imutavel() -> None:
    record = Record(
        sha256="a" * 64,
        bucket="raw",
        key="raw/o/t/2026/01/01/" + "a" * 64,
        size=1,
        content_type="text/plain",
        origem="o",
        tipo="t",
        coletado_em=datetime(2026, 1, 1, tzinfo=UTC),
    )

    with pytest.raises(AttributeError):
        record.sha256 = "b" * 64  # type: ignore[misc]


def test_record_nasce_catalogado() -> None:
    record = Record(
        sha256="a" * 64,
        bucket="raw",
        key="k",
        size=1,
        content_type="text/plain",
        origem="o",
        tipo="t",
        coletado_em=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert record.state is UploadState.CATALOGED
    assert record.metadados == {}


def test_objetoref_carrega_hash_no_caminho() -> None:
    sha = "c" * 64
    ref = ObjectRef(bucket="raw", key=f"raw/o/t/2026/01/01/{sha}", sha256=sha, size=0, content_type="")

    assert ref.sha256 in ref.key


def test_duplicado_e_ingerror_e_expoe_o_hash() -> None:
    erro = DuplicateObjectError("d" * 64)

    assert isinstance(erro, IngestError)
    assert erro.sha256 == "d" * 64


@pytest.mark.parametrize(
    "erro", [UnsupportedObjectError, IntegrityMismatchError, DuplicateObjectError]
)
def test_todos_os_erros_derivam_de_ingerror(erro: type[IngestError]) -> None:
    assert issubclass(erro, IngestError)


def test_portas_sao_protocolos() -> None:
    """Portas não devem virar ABC com herança obrigatória.

    Implementações reais (adaptadores de Garage e PostgreSQL) não podem precisar
    importar o núcleo para existir. `Protocol` preserva isso.
    """
    for porta in (ObjectStore, Catalog, Clock):
        assert getattr(porta, "_is_protocol", False) is True
