"""Testes de ingestão.

O critério de pronto da Onda 1 é: "ingerir o mesmo arquivo 2x → 1 Record".
Os testes abaixo cobrem esse critério e os modos de falha que o cercam.

Regra de escrita: cada teste tem um único motivo para falhar. Nada de teste
que verifica cinco coisas — quando quebra, não se sabe o quê.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lakecore import IngestRequest, IntegrityMismatchError, UnsupportedObjectError
from lakecore.fakes import FakeCatalog, FakeObjectStore, FixedClock
from lakecore import ingestion as modulo
from lakecore.ingestion import classify, hash_file, ingest

CONTEUDO = b"datalake-doomsday: o dado bruto e o ativo\n"


@pytest.fixture
def arquivo(tmp_path: Path) -> Path:
    destino = tmp_path / "nota.txt"
    destino.write_bytes(CONTEUDO)
    return destino


@pytest.fixture
def store() -> FakeObjectStore:
    return FakeObjectStore()


@pytest.fixture
def catalog() -> FakeCatalog:
    return FakeCatalog()


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock()


def _ingerir(
    arquivo: Path,
    *,
    store: FakeObjectStore,
    catalog: FakeCatalog,
    clock: FixedClock,
    origem: str = "pendrive",
    tipo: str | None = None,
) -> object:
    return ingest(
        IngestRequest(path=str(arquivo), origem=origem, tipo=tipo),
        store=store,
        catalog=catalog,
        clock=clock,
    )


# --- critério de pronto da onda -------------------------------------------------


def test_ingere_arquivo_novo(
    arquivo: Path, store: FakeObjectStore, catalog: FakeCatalog, clock: FixedClock
) -> None:
    resultado = _ingerir(arquivo, store=store, catalog=catalog, clock=clock)

    assert resultado.duplicate is False
    assert resultado.record.origem == "pendrive"
    assert resultado.record.size == len(CONTEUDO)
    assert store.escritas == 1
    assert len(catalog.registros) == 1


def test_mesmo_arquivo_duas_vezes_nao_duplica(
    arquivo: Path, store: FakeObjectStore, catalog: FakeCatalog, clock: FixedClock
) -> None:
    primeiro = _ingerir(arquivo, store=store, catalog=catalog, clock=clock)
    segundo = _ingerir(arquivo, store=store, catalog=catalog, clock=clock)

    assert primeiro.duplicate is False
    assert segundo.duplicate is True
    assert segundo.record.sha256 == primeiro.record.sha256
    assert len(catalog.registros) == 1
    assert store.escritas == 1, "a segunda ingestão não deve reescrever o objeto"


def test_conteudo_igual_com_nome_diferente_e_o_mesmo_objeto(
    tmp_path: Path, store: FakeObjectStore, catalog: FakeCatalog, clock: FixedClock
) -> None:
    """Idempotência é por conteúdo, não por nome — renomear não duplica."""
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_bytes(CONTEUDO)
    b.write_bytes(CONTEUDO)

    r1 = _ingerir(a, store=store, catalog=catalog, clock=clock)
    r2 = _ingerir(b, store=store, catalog=catalog, clock=clock)

    assert r1.record.sha256 == r2.record.sha256
    assert r2.duplicate is True
    assert len(catalog.registros) == 1


def test_arquivo_vazio_e_ingerivel(
    tmp_path: Path, store: FakeObjectStore, catalog: FakeCatalog, clock: FixedClock
) -> None:
    vazio = tmp_path / "vazio.txt"
    vazio.write_bytes(b"")

    resultado = _ingerir(vazio, store=store, catalog=catalog, clock=clock)

    assert resultado.record.size == 0
    assert resultado.record.sha256 == hashlib.sha256(b"").hexdigest()


# --- falhas esperadas -----------------------------------------------------------


def test_origem_vazia_e_rejeitada(
    arquivo: Path, store: FakeObjectStore, catalog: FakeCatalog, clock: FixedClock
) -> None:
    with pytest.raises(UnsupportedObjectError, match="origem é obrigatória"):
        _ingerir(arquivo, store=store, catalog=catalog, clock=clock, origem="   ")


def test_arquivo_inexistente_e_rejeitado(
    tmp_path: Path, store: FakeObjectStore, catalog: FakeCatalog, clock: FixedClock
) -> None:
    with pytest.raises(UnsupportedObjectError, match="não encontrado"):
        _ingerir(
            tmp_path / "nao-existe.txt", store=store, catalog=catalog, clock=clock
        )


def test_diretorio_e_rejeitado(
    tmp_path: Path, store: FakeObjectStore, catalog: FakeCatalog, clock: FixedClock
) -> None:
    with pytest.raises(UnsupportedObjectError, match="diretório não é ingerível"):
        _ingerir(tmp_path, store=store, catalog=catalog, clock=clock)


def test_arquivo_acima_do_limite_e_rejeitado(
    arquivo: Path, store: FakeObjectStore, catalog: FakeCatalog, clock: FixedClock
) -> None:
    with pytest.raises(UnsupportedObjectError, match="acima do limite"):
        ingest(
            IngestRequest(path=str(arquivo), origem="x"),
            store=store,
            catalog=catalog,
            clock=clock,
            tamanho_maximo=1,
        )


def test_storage_que_nao_confirma_a_escrita_falha_fechado(
    arquivo: Path, catalog: FakeCatalog, clock: FixedClock
) -> None:
    """Storage aceita a chamada e perde o objeto → não pode catalogar.

    O contrário produziria linha no catálogo apontando para objeto inexistente.
    """
    store = FakeObjectStore()
    store.put = lambda ref, data: None  # type: ignore[method-assign]

    with pytest.raises(IntegrityMismatchError, match="não confirmou"):
        _ingerir(arquivo, store=store, catalog=catalog, clock=clock)

    assert catalog.registros == {}, "nada deve ser catalogado se o objeto não existe"


def test_arquivo_modificado_durante_ingestao_falha_fechado(
    arquivo: Path,
    store: FakeObjectStore,
    catalog: FakeCatalog,
    clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Protege contra arquivo alterado entre o hash e a escrita."""
    original = hash_file

    def hash_e_modifica(path: Path, **kwargs: object) -> tuple[str, int]:
        resultado = original(path, **kwargs)
        path.write_bytes(b"conteudo diferente")
        return resultado

    monkeypatch.setattr(modulo, "hash_file", hash_e_modifica)

    with pytest.raises(IntegrityMismatchError, match="mudou entre o hash"):
        _ingerir(arquivo, store=store, catalog=catalog, clock=clock)


# --- derivados ------------------------------------------------------------------


def test_tipo_pode_ser_sobrescrito_pelo_chamador(
    arquivo: Path, store: FakeObjectStore, catalog: FakeCatalog, clock: FixedClock
) -> None:
    resultado = _ingerir(
        arquivo, store=store, catalog=catalog, clock=clock, tipo="documento"
    )

    assert resultado.record.tipo == "documento"
    assert "/documento/" in resultado.record.key


def test_metadados_preservam_nome_original(
    arquivo: Path, store: FakeObjectStore, catalog: FakeCatalog, clock: FixedClock
) -> None:
    resultado = _ingerir(arquivo, store=store, catalog=catalog, clock=clock)

    assert resultado.record.metadados["nome_original"] == "nota.txt"


def test_coletado_em_vem_do_relogio_injetado(
    arquivo: Path, store: FakeObjectStore, catalog: FakeCatalog
) -> None:
    momento = datetime(2027, 3, 4, 5, 6, tzinfo=UTC)
    resultado = _ingerir(
        arquivo, store=store, catalog=catalog, clock=FixedClock(momento=momento)
    )

    assert resultado.record.coletado_em == momento
    assert "/2027/03/04/" in resultado.record.key


@pytest.mark.parametrize(
    ("nome", "tipo", "content_type"),
    [
        ("a.txt", "texto", "text/plain"),
        ("a.md", "texto", "text/markdown"),
        ("a.csv", "texto", "text/csv"),
        ("a.pdf", "pdf", "application/pdf"),
        ("a.png", "imagem", "image/png"),
        ("a.jpg", "imagem", "image/jpeg"),
        ("sem_extensao", "binario", "application/octet-stream"),
        ("a.desconhecido", "desconhecido", "application/octet-stream"),
    ],
)
def test_classificacao_por_extensao(nome: str, tipo: str, content_type: str) -> None:
    assert classify(Path(nome)) == (tipo, content_type)


def test_hash_de_arquivo_grande_usa_streaming(tmp_path: Path) -> None:
    """Arquivo maior que o bloco de leitura ainda produz o hash correto."""
    grande = tmp_path / "grande.bin"
    dados = b"x" * ((1 << 20) * 2 + 7)
    grande.write_bytes(dados)

    sha, tamanho = hash_file(grande)

    assert tamanho == len(dados)
    assert sha == hashlib.sha256(dados).hexdigest()
