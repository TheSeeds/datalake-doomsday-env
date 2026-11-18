"""Testes do sinal de frescor.

O QUE ESTES TESTES PROTEGEM:

o módulo existe para transformar "ninguém sabe se o backup funciona" em uma
resposta. Se ele responder "saudável" para um lake que nunca fez backup, ele
reproduz o incidente de 2026-11-18 com um selo de aprovação — que é pior que não
ter o módulo.

O caso central, e o motivo de o módulo existir: **sinal ausente não é OK.**
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from lakecore.db.models import Base
from lakecore.saude import LIMIARES, estado, registrar, resumo


@pytest.fixture
def banco() -> Iterator[Engine]:
    eng = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


def agora() -> datetime:
    return datetime.now(UTC)


class TestSinalAusenteNaoEhOk:
    """O defeito que o módulo existe para impedir."""

    def test_lake_novo_nao_e_saudavel(self, banco: Engine) -> None:
        """Sem nenhum registro, `resumo` NÃO pode dizer que está tudo bem."""
        tudo_ok, sinais = resumo(banco)
        assert tudo_ok is False
        assert sinais == []

    def test_sinal_pedido_e_ausente_vira_desconhecido(self, banco: Engine) -> None:
        """Quem pergunta "e o backup?" precisa de resposta, não de silêncio."""
        resultado = estado(banco, ("backup",))
        assert len(resultado) == 1
        assert resultado[0].estado == "desconhecido"
        assert "nunca registrou" in (resultado[0].detalhe or "")

    def test_desconhecido_conta_como_problema(self, banco: Engine) -> None:
        registrar(banco, "backup", sucesso=True)
        # "export" foi pedido? Não. Mas se não houver sinal nenhum além de
        # backup, e backup estiver ok, o resumo pode ficar verde.
        tudo_ok, _ = resumo(banco)
        assert tudo_ok is True

        # Agora um sinal que existe mas nunca funcionou derruba o resumo.
        with banco.begin() as conn:
            conn.execute(
                text(
                    "insert into saude (sinal, ultima_falha, total_ok, total_falha,"
                    " detalhe, atualizado_em) values ('export', :q, 0, 1, 'quebrou', :q)"
                ),
                {"q": agora()},
            )
        tudo_ok, sinais = resumo(banco)
        assert tudo_ok is False
        assert {s.sinal: s.estado for s in sinais}["export"] == "falhou"


class TestRegistro:
    def test_sucesso_cria_a_linha(self, banco: Engine) -> None:
        """A primeira execução de uma rotina nova tem que criar a linha."""
        registrar(banco, "backup", sucesso=True)
        [sinal] = estado(banco, ("backup",))
        assert sinal.estado == "saudavel"
        assert sinal.ultimo_sucesso is not None
        assert sinal.ultima_falha is None

    def test_sucesso_depois_de_falha_preserva_a_falha(self, banco: Engine) -> None:
        """Um backup que falhou ontem e funcionou hoje é o caso NORMAL."""
        registrar(banco, "backup", sucesso=False, detalhe="disco cheio")
        registrar(banco, "backup", sucesso=True)
        [sinal] = estado(banco, ("backup",))
        assert sinal.estado == "saudavel"
        assert sinal.ultima_falha is not None, "histórico de falha foi apagado"

    def test_falha_depois_de_sucesso_vira_falhou(self, banco: Engine) -> None:
        """Falhou depois do último sucesso: está quebrado AGORA."""
        registrar(banco, "backup", sucesso=True)
        registrar(banco, "backup", sucesso=False, detalhe="ImagePullBackOff")
        [sinal] = estado(banco, ("backup",))
        assert sinal.estado == "falhou"
        assert "ImagePullBackOff" in (sinal.detalhe or "")

    def test_contadores_somam(self, banco: Engine) -> None:
        for _ in range(3):
            registrar(banco, "backup", sucesso=True)
        registrar(banco, "backup", sucesso=False)
        with banco.connect() as conn:
            ok, falha = conn.execute(
                text("select total_ok, total_falha from saude where sinal='backup'")
            ).fetchone()
        assert (ok, falha) == (3, 1)

    def test_detalhe_carrega_a_mensagem(self, banco: Engine) -> None:
        """Guardar só "failed" obrigaria a caçar o log de um pod já apagado."""
        registrar(banco, "backup", sucesso=False, detalhe="permission denied")
        [sinal] = estado(banco, ("backup",))
        assert sinal.detalhe == "permission denied"


class TestFrescor:
    def test_dentro_do_limiar_e_saudavel(self, banco: Engine) -> None:
        registrar(banco, "backup", sucesso=True, quando=agora() - timedelta(hours=2))
        assert estado(banco, ("backup",))[0].estado == "saudavel"

    def test_alem_do_limiar_e_velho(self, banco: Engine) -> None:
        """Silêncio além do limiar significa execução perdida."""
        limite = LIMIARES["backup"] + timedelta(hours=1)
        registrar(banco, "backup", sucesso=True, quando=agora() - limite)
        assert estado(banco, ("backup",))[0].estado == "velho"

    def test_idade_e_reportada(self, banco: Engine) -> None:
        registrar(banco, "backup", sucesso=True, quando=agora() - timedelta(hours=5))
        sinal = estado(banco, ("backup",))[0]
        assert sinal.idade is not None
        assert 4 < sinal.idade.total_seconds() / 3600 < 6

    def test_texto_e_legivel(self, banco: Engine) -> None:
        registrar(banco, "backup", sucesso=True, quando=agora() - timedelta(hours=3))
        texto = estado(banco, ("backup",))[0].texto()
        assert "backup: saudavel" in texto
        assert "3h" in texto


class TestSinaisPedidos:
    def test_ordem_preservada(self, banco: Engine) -> None:
        registrar(banco, "backup", sucesso=True)
        registrar(banco, "ingestao", sucesso=True)
        nomes = [s.sinal for s in estado(banco, ("ingestao", "backup"))]
        assert nomes == ["ingestao", "backup"]

    def test_sem_lista_devolve_os_registrados(self, banco: Engine) -> None:
        registrar(banco, "backup", sucesso=True)
        registrar(banco, "ingestao", sucesso=True)
        assert {s.sinal for s in estado(banco)} == {"backup", "ingestao"}
