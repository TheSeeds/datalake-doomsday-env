"""Testes dos adaptadores contra infraestrutura REAL.

Diferente do resto da suíte: aqui não há fake. S3 e PostgreSQL de verdade, porque
o que falha em adaptador é exatamente o que o fake esconde — assinatura, header,
permissão, encoding, tipo de coluna.

Pula automaticamente se as variáveis de ambiente não estiverem definidas, para que
`make ci` continue rodando sem Docker nem cluster.

    S3_ENDPOINT / S3_ACCESS_KEY / S3_SECRET_KEY
    LAKECORE_TEST_PG_URL
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lakecore.adapters.s3_store import S3ObjectStore, from_env
from lakecore.errors import UnsupportedObjectError
from lakecore.models import ObjectRef, Record

pytestmark = pytest.mark.integration


def _tem_s3() -> bool:
    return all(os.environ.get(k) for k in ("S3_ENDPOINT", "S3_ACCESS_KEY", "S3_SECRET_KEY"))


@pytest.fixture
def store() -> Iterator[S3ObjectStore]:
    if not _tem_s3():
        pytest.skip("S3_* não definidas: teste exige Garage real")
    s = from_env(dict(os.environ))
    s.garantir_bucket("raw")
    yield s


def _ref(sha: str, *, prefixo: str = "teste-adaptador") -> ObjectRef:
    return ObjectRef(
        bucket="raw",
        key=f"raw/{prefixo}/texto/2026/11/18/{sha}",
        sha256=sha,
        size=0,
        content_type="text/plain",
    )


class TestS3ObjectStore:
    def test_put_e_exists(self, store: S3ObjectStore) -> None:
        dados = b"conteudo do lake\n"
        import hashlib

        sha = hashlib.sha256(dados).hexdigest()
        ref = _ref(sha)

        store.put(ref, dados)

        assert store.exists("raw", ref.key) is True

    def test_exists_falso_para_chave_ausente(self, store: S3ObjectStore) -> None:
        assert store.exists("raw", f"raw/nao-existe/{uuid.uuid4().hex}") is False

    def test_put_grava_metadados_no_objeto(self, store: S3ObjectStore) -> None:
        """Metadados no objeto sobrevivem à perda do catálogo.

        O catálogo é reconstruível a partir do storage; o contrário não. Por isso
        `sha256` vai também como metadado do objeto, não só na linha do banco.
        """
        dados = b"com metadados\n"
        import hashlib

        sha = hashlib.sha256(dados).hexdigest()
        ref = ObjectRef(
            bucket="raw",
            key=f"raw/teste-meta/texto/2026/11/18/{sha}",
            sha256=sha,
            size=len(dados),
            content_type="text/plain",
        )
        store.put(ref, dados)

        meta = store._client.head_object(Bucket="raw", Key=ref.key)["Metadata"]  # noqa: SLF001
        assert meta["sha256"] == sha
        assert meta["tamanho"] == str(len(dados))

    def test_garantir_bucket_e_idempotente(self, store: S3ObjectStore) -> None:
        store.garantir_bucket("raw")
        store.garantir_bucket("raw")

    def test_from_env_falha_fechado_sem_credencial(self) -> None:
        with pytest.raises(RuntimeError, match="variáveis ausentes"):
            from_env({"S3_ENDPOINT": "http://x"})


class TestIngestaoReal:
    """`lakecore.ingest()` contra Garage + PostgreSQL de verdade.

    É o critério da Onda 4: arquivo → objeto no storage **e** linha no catálogo,
    idempotente nas duas escritas.
    """

    @pytest.fixture
    def ambiente(self, store: S3ObjectStore, tmp_path: Path) -> Iterator[dict]:
        pg = os.environ.get("LAKECORE_TEST_PG_URL")
        if not pg:
            pytest.skip("LAKECORE_TEST_PG_URL não definida")

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from lakecore.db.catalog import SqlCatalog
        from lakecore.db.models import Base

        engine = create_engine(pg, future=True)
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        catalog = SqlCatalog(sessionmaker(bind=engine, expire_on_commit=False))

        yield {"store": store, "catalog": catalog, "engine": engine, "tmp": tmp_path}

        Base.metadata.drop_all(engine)
        engine.dispose()

    def test_arquivo_vira_objeto_e_linha(self, ambiente: dict) -> None:
        from lakecore.ingestion import ingest

        arquivo = ambiente["tmp"] / "nota.txt"
        arquivo.write_text("primeira ingestao real\n")

        resultado = ingest(
            __import__("lakecore.models", fromlist=["IngestRequest"]).IngestRequest(
                path=str(arquivo), origem="teste-real"
            ),
            store=ambiente["store"],
            catalog=ambiente["catalog"],
            clock=__import__("lakecore.fakes", fromlist=["FixedClock"]).FixedClock(),
        )

        from sqlalchemy import text

        with ambiente["engine"].connect() as conn:
            linhas = conn.execute(text("select count(*) from objects")).scalar_one()

        assert resultado.duplicate is False
        assert linhas == 1
        assert ambiente["store"].exists("raw", resultado.record.key) is True

    def test_duas_ingestoes_uma_linha_um_objeto(self, ambiente: dict) -> None:
        """O critério literal da Onda 4."""
        from lakecore.fakes import FixedClock
        from lakecore.ingestion import ingest
        from lakecore.models import IngestRequest

        arquivo = ambiente["tmp"] / "idem.txt"
        arquivo.write_text("mesmo conteudo\n")
        relogio = FixedClock()

        primeira = ingest(
            IngestRequest(path=str(arquivo), origem="teste-real"),
            store=ambiente["store"],
            catalog=ambiente["catalog"],
            clock=relogio,
        )
        segunda = ingest(
            IngestRequest(path=str(arquivo), origem="teste-real"),
            store=ambiente["store"],
            catalog=ambiente["catalog"],
            clock=relogio,
        )

        from sqlalchemy import text

        with ambiente["engine"].connect() as conn:
            linhas = conn.execute(text("select count(*) from objects")).scalar_one()

        assert primeira.duplicate is False
        assert segunda.duplicate is True
        assert linhas == 1
        assert primeira.record.key == segunda.record.key

    def test_objeto_grande_grava_bloco_no_disco(self, ambiente: dict) -> None:
        """Objetos <1MiB são inlinados no LMDB; só >1MiB geram bloco em data/.

        Lição da Onda 3: testar com 41 bytes "passa" sem exercitar armazenamento
        de bloco. Aqui usa 2 MiB de propósito.
        """
        from lakecore.fakes import FixedClock
        from lakecore.ingestion import ingest
        from lakecore.models import IngestRequest

        arquivo = ambiente["tmp"] / "grande.bin"
        arquivo.write_bytes(os.urandom(2 * 1024 * 1024))

        resultado = ingest(
            IngestRequest(path=str(arquivo), origem="teste-real", tipo="binario"),
            store=ambiente["store"],
            catalog=ambiente["catalog"],
            clock=FixedClock(),
        )

        assert resultado.record.size == 2 * 1024 * 1024
        assert ambiente["store"].exists("raw", resultado.record.key)
