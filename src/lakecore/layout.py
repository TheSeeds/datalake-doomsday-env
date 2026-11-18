"""Layout determinístico do storage bruto.

    raw/{origem}/{tipo}/{YYYY}/{MM}/{DD}/{sha256}

Determinístico, idempotente e portável entre Garage e qualquer S3. O `sha256`
como último segmento é o que dispensa tabela de deduplicação no storage: duas
ingestões do mesmo conteúdo geram a mesma chave, e a segunda é um no-op.

A função é pura e mora no núcleo, não no adaptador de storage, porque o layout é
parte do contrato do lake — trocar de backend não pode mudar onde o dado está.
"""

from __future__ import annotations

import re
from datetime import datetime

_SEGMENTO_INVALIDO = re.compile(r"[^a-z0-9._-]+")

#: Profundidade máxima aceita por segmento de origem/tipo. Valores maiores são
#: truncados para não estourar limites de chave em backends S3.
_MAX_SEGMENTO = 64


def _normalizar(segmento: str, *, padrao: str) -> str:
    """Reduz um segmento livre a `[a-z0-9._-]`, sem barras e sem `..`.

    O caminho vem de entrada do usuário (`origem`), então precisa ser saneado:
    um `origem="../../etc"` não pode escapar do prefixo `raw/`.
    """
    limpo = _SEGMENTO_INVALIDO.sub("-", segmento.strip().lower()).strip("-.")

    if not limpo or set(limpo) == {"."}:
        return padrao

    return limpo[:_MAX_SEGMENTO]


def raw_key(
    *,
    origem: str,
    tipo: str,
    coletado_em: datetime,
    sha256: str,
    bucket_prefixo: str = "raw",
) -> str:
    """Monta a chave do objeto bruto.

    Levanta `ValueError` para `sha256` que não seja 64 caracteres hexadecimais:
    um hash malformado viraria diretório inválido e o erro apareceria longe
    daqui.
    """
    if len(sha256) != 64 or not all(c in "0123456789abcdef" for c in sha256.lower()):
        raise ValueError(f"sha256 inválido: {sha256!r}")

    if coletado_em.tzinfo is None:
        raise ValueError("coletado_em precisa ser timezone-aware")

    return "/".join(
        (
            _normalizar(bucket_prefixo, padrao="raw"),
            _normalizar(origem, padrao="desconhecida"),
            _normalizar(tipo, padrao="binario"),
            f"{coletado_em.year:04d}",
            f"{coletado_em.month:02d}",
            f"{coletado_em.day:02d}",
            sha256.lower(),
        )
    )
