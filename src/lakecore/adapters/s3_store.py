"""Adaptador de `ObjectStore` sobre S3 (Garage).

O domínio (`lakecore`) declara a porta; este módulo cumpre. Nada de regra de
negócio aqui: só traduzir `put`/`exists` para chamadas S3.

Duas decisões que vêm do ADR-011:

1. **Sem `get`.** O papel `ingest` tem chave write-only no prefixo `raw/`. Um
   ingestor comprometido não deve conseguir ler o acervo que ajudou a gravar.
   A porta do domínio também não exige `get` — o tipo reflete a política.
2. **`exists` via `head_object`.** Se a chave não tem permissão de leitura, o
   `head` ainda funciona (é metadado), então a verificação pós-escrita continua
   válida com credencial write-only.
"""

from __future__ import annotations

import logging
from typing import Any

import boto3
from botocore.exceptions import ClientError

from lakecore.errors import StorageUnavailableError
from lakecore.models import ObjectRef

log = logging.getLogger(__name__)


class S3ObjectStore:
    """`ObjectStore` sobre qualquer S3 compatível (Garage, AWS, MinIO)."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        region: str = "garage",
    ) -> None:
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )

    def put(self, ref: ObjectRef, data: bytes) -> None:
        self._client.put_object(
            Bucket=ref.bucket,
            Key=ref.key,
            Body=data,
            ContentType=ref.content_type,
            # Metadados no próprio objeto: sobrevivem a uma perda do catálogo.
            # O catálogo é reconstruível a partir do storage; o contrário não.
            Metadata={
                "sha256": ref.sha256,
                "tamanho": str(ref.size),
            },
        )
        log.info("objeto gravado", extra={"bucket": ref.bucket, "key": ref.key})

    def exists(self, bucket: str, key: str) -> bool:
        """Verifica presença. **Exige credencial com leitura.**

        Levanta `StorageUnavailableError` quando o storage responde 403: com
        chave write-only não há como distinguir "não existe" de "não posso ver",
        e devolver `False` seria mentir — foi exatamente isso que produziu o
        HTTP 500 na primeira ingestão real.

        A ingestão **não** chama este método (ADR-013). Ele existe para
        verificação com credencial de leitura e para o `restore drill`.
        """
        try:
            self._client.head_object(Bucket=bucket, Key=key)
        except ClientError as exc:
            codigo = exc.response.get("Error", {}).get("Code", "")
            if codigo in {"404", "NoSuchKey", "NotFound"}:
                return False
            if codigo in {"403", "AccessDenied"}:
                raise StorageUnavailableError(
                    f"storage negou leitura de {bucket}/{key}: credencial "
                    "write-only não distingue 'ausente' de 'sem permissão'. "
                    "Use credencial com permissão R para verificar."
                ) from exc
            raise
        return True

    def garantir_bucket(self, bucket: str) -> None:
        """Cria o bucket se não existir.

        Idempotente de propósito: chamado na inicialização, e reinício de pod não
        deve falhar por "bucket já existe".
        """
        try:
            self._client.head_bucket(Bucket=bucket)
        except ClientError:
            self._client.create_bucket(Bucket=bucket)
            log.info("bucket criado", extra={"bucket": bucket})


def from_env(env: dict[str, str]) -> S3ObjectStore:
    """Constrói a partir de variáveis de ambiente.

    Falha fechado: sem endpoint ou credencial, levanta em vez de criar um cliente
    que falharia na primeira escrita com erro obscuro.
    """
    faltando = [
        nome
        for nome in ("S3_ENDPOINT", "S3_ACCESS_KEY", "S3_SECRET_KEY")
        if not env.get(nome)
    ]
    if faltando:
        raise RuntimeError(f"variáveis ausentes: {', '.join(faltando)}")

    return S3ObjectStore(
        endpoint_url=env["S3_ENDPOINT"],
        access_key=env["S3_ACCESS_KEY"],
        secret_key=env["S3_SECRET_KEY"],
        region=env.get("S3_REGION", "garage"),
    )


def config_extra(env: dict[str, Any]) -> dict[str, Any]:
    """Metadados de diagnóstico devolvidos por `/health`. Sem segredo."""
    return {
        "endpoint": env.get("S3_ENDPOINT"),
        "region": env.get("S3_REGION", "garage"),
    }
