"""Testes do layout do storage bruto.

Cobrem o que pode dar errado em chave de objeto: entrada suja do usuário,
timestamp ingênuo e hash malformado. Layout errado não dá erro — dá dado no
lugar errado, que é pior.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from lakecore.layout import raw_key

SHA = "a" * 64
MOMENTO = datetime(2026, 11, 17, 14, 30, tzinfo=UTC)


def test_layout_completo() -> None:
    key = raw_key(origem="pendrive", tipo="pdf", coletado_em=MOMENTO, sha256=SHA)

    assert key == f"raw/pendrive/pdf/2026/11/17/{SHA}"


def test_sha256_e_normalizado_para_minusculo() -> None:
    key = raw_key(origem="x", tipo="log", coletado_em=MOMENTO, sha256="B" * 64)

    assert key.endswith("b" * 64)


def test_origem_com_travessia_de_caminho_nao_escapa_do_prefixo() -> None:
    key = raw_key(origem="../../etc", tipo="passwd", coletado_em=MOMENTO, sha256=SHA)

    assert key.startswith("raw/")
    assert ".." not in key
    assert key == f"raw/etc/passwd/2026/11/17/{SHA}"


def test_segmento_vazio_cai_no_padrao() -> None:
    key = raw_key(origem="   ", tipo="", coletado_em=MOMENTO, sha256=SHA)

    assert key == f"raw/desconhecida/binario/2026/11/17/{SHA}"


def test_segmento_longo_e_truncado() -> None:
    key = raw_key(origem="o" * 200, tipo="t", coletado_em=MOMENTO, sha256=SHA)

    segmento_origem = key.split("/")[1]
    assert len(segmento_origem) == 64


def test_data_usa_zero_a_esquerda() -> None:
    janeiro = datetime(2026, 1, 5, tzinfo=UTC)

    key = raw_key(origem="o", tipo="t", coletado_em=janeiro, sha256=SHA)

    assert "/2026/01/05/" in key


def test_timestamp_ingenuo_e_rejeitado() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        raw_key(origem="o", tipo="t", coletado_em=datetime(2026, 1, 1), sha256=SHA)


@pytest.mark.parametrize("sha_invalido", ["", "abc", "z" * 64, SHA + "0"])
def test_sha256_malformado_e_rejeitado(sha_invalido: str) -> None:
    with pytest.raises(ValueError, match="sha256 inválido"):
        raw_key(origem="o", tipo="t", coletado_em=MOMENTO, sha256=sha_invalido)
