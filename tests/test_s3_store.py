"""Testes do adaptador S3.

O caso que motivou este arquivo: `exists()` com chave **write-only** (ADR-011).
O Garage nega `HeadObject` com 403 antes de revelar se o objeto existe, e tratar
403 como erro derrubou a ingestão com HTTP 500. Tratar 403 como "não existe" é
seguro aqui porque a escrita é idempotente por chave — mas isso precisa de teste,
não de confiança.

Estes testes usam um cliente falso, sem rede: verificam o **mapeamento de erro**,
que é onde estava o defeito. O comportamento real contra o Garage fica em
`tests/integration/test_adapters.py`.
"""

from __future__ import annotations

import hashlib

import pytest
from botocore.exceptions import ClientError

from lakecore.adapters.s3_store import S3ObjectStore, from_env
from lakecore.errors import StorageUnavailableError
from lakecore.models import ObjectRef


class ClienteFalso:
    """Cliente boto3 mínimo, com erros injetáveis por operação."""

    def __init__(self) -> None:
        self.erro_head: ClientError | None = None
        self.erro_put: ClientError | None = None
        self.puts: list[dict] = []

    def head_object(self, **kwargs: object) -> dict:
        if self.erro_head is not None:
            raise self.erro_head
        return {}

    def put_object(self, **kwargs: object) -> dict:
        if self.erro_put is not None:
            raise self.erro_put
        self.puts.append(dict(kwargs))
        return {}


def _erro(codigo: str, operacao: str = "HeadObject") -> ClientError:
    return ClientError({"Error": {"Code": codigo, "Message": "teste"}}, operacao)


def _store(cliente: ClienteFalso) -> S3ObjectStore:
    store = S3ObjectStore.__new__(S3ObjectStore)
    store._client = cliente  # type: ignore[attr-defined]
    return store


def _ref() -> ObjectRef:
    dados = b"conteudo\n"
    return ObjectRef(
        bucket="raw",
        key=f"raw/x/texto/2026/11/18/{hashlib.sha256(dados).hexdigest()}",
        sha256=hashlib.sha256(dados).hexdigest(),
        size=len(dados),
        content_type="text/plain",
    )


class TestExists:
    def test_objeto_presente(self) -> None:
        assert _store(ClienteFalso()).exists("raw", "k") is True

    @pytest.mark.parametrize("codigo", ["404", "NoSuchKey", "NotFound"])
    def test_ausente_devolve_false(self, codigo: str) -> None:
        cliente = ClienteFalso()
        cliente.erro_head = _erro(codigo)

        assert _store(cliente).exists("raw", "k") is False

    @pytest.mark.parametrize("codigo", ["403", "AccessDenied"])
    def test_chave_write_only_levanta_em_vez_de_mentir(self, codigo: str) -> None:
        """ADR-013: 403 significa "não posso ver", não "não existe".

        A primeira versão devolvia `False` aqui. Isso derrubou a ingestão real
        com HTTP 500 por um caminho torto, e pior: registrava como fato algo que
        nunca foi verificado. O contrato correto é **falhar alto** — quem chama
        recebe a informação de que a credencial não permite responder.
        """
        cliente = ClienteFalso()
        cliente.erro_head = _erro(codigo)

        with pytest.raises(StorageUnavailableError, match="write-only"):
            _store(cliente).exists("raw", "k")

    def test_erro_desconhecido_propaga(self) -> None:
        """Não transformar qualquer falha em "não existe".

        Se o storage está fora do ar, `exists` deve explodir: assumir "não
        existe" e gravar esconderia indisponibilidade.
        """
        cliente = ClienteFalso()
        cliente.erro_head = _erro("ServiceUnavailable")

        with pytest.raises(ClientError):
            _store(cliente).exists("raw", "k")


class TestPut:
    def test_grava_metadados_de_integridade(self) -> None:
        cliente = ClienteFalso()
        ref = _ref()

        _store(cliente).put(ref, b"conteudo\n")

        assert len(cliente.puts) == 1
        meta = cliente.puts[0]["Metadata"]
        assert meta["sha256"] == ref.sha256
        assert meta["tamanho"] == str(ref.size)

    def test_falha_de_escrita_propaga(self) -> None:
        cliente = ClienteFalso()
        cliente.erro_put = _erro("AccessDenied", operacao="PutObject")

        with pytest.raises(ClientError):
            _store(cliente).put(_ref(), b"conteudo\n")


class TestFromEnv:
    def test_falha_fechado_sem_credencial(self) -> None:
        with pytest.raises(RuntimeError, match="variáveis ausentes"):
            from_env({"S3_ENDPOINT": "http://x"})

    def test_lista_todas_as_ausentes(self) -> None:
        with pytest.raises(RuntimeError) as exc:
            from_env({})

        assert "S3_ENDPOINT" in str(exc.value)
        assert "S3_ACCESS_KEY" in str(exc.value)
        assert "S3_SECRET_KEY" in str(exc.value)
