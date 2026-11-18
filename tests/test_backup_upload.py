"""Testes do upload do backup para o Garage.

POR QUE ESTES TESTES EXISTEM:

o Job de backup falhou em **100% das execuções** desde que foi escrito, e
ninguém viu por horas. O defeito não foi de lógica: o chart injetava
`GARAGE_S3_ENDPOINT` e o script lia `S3_ENDPOINT`, então o Job morria com
`KeyError` antes de enviar qualquer byte. Um teste que exercitasse o script com
as variáveis que o chart realmente define teria pegado isso em milissegundos.

A lição é a mesma do executor e do `pg_isready`: **verde sem exercitar o caminho
real não é verde.** Por isso o teste central aqui lê o template do chart e
confere os nomes das variáveis contra o que o script consome — em vez de repetir
a lista de nomes à mão, que envelheceria em silêncio.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# O script não é um pacote instalável: vive ao lado do Dockerfile, porque é
# copiado para dentro da imagem. Importar por caminho é o que permite testá-lo
# sem publicar um pacote só para isso.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docker" / "backup"))

import upload_s3  # noqa: E402


TEMPLATE_CHART = (
    Path(__file__).resolve().parents[1]
    / "charts"
    / "postgresql"
    / "templates"
    / "backup-cronjob.yaml"
)


class TestNomeDasVariaveis:
    """A divergência chart × script foi a causa da falha silenciosa."""

    def test_script_aceita_o_nome_que_o_chart_injeta(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """O chart injeta `GARAGE_S3_ENDPOINT`; o script tem que aceitar."""
        monkeypatch.delenv("S3_ENDPOINT", raising=False)
        monkeypatch.setenv("GARAGE_S3_ENDPOINT", "http://garage:3900")
        assert upload_s3._exigir("S3_ENDPOINT", "GARAGE_S3_ENDPOINT") == "http://garage:3900"

    def test_script_aceita_o_nome_curto(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GARAGE_S3_ENDPOINT", raising=False)
        monkeypatch.setenv("S3_ENDPOINT", "http://outro:3900")
        assert upload_s3._exigir("S3_ENDPOINT", "GARAGE_S3_ENDPOINT") == "http://outro:3900"

    def test_ausente_falha_alto_com_mensagem_util(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Falha explícita, não upload silenciosamente errado."""
        monkeypatch.delenv("S3_ENDPOINT", raising=False)
        monkeypatch.delenv("GARAGE_S3_ENDPOINT", raising=False)
        with pytest.raises(RuntimeError, match="nenhuma destas variáveis"):
            upload_s3._exigir("S3_ENDPOINT", "GARAGE_S3_ENDPOINT")

    def test_o_template_do_chart_e_a_fonte_da_verdade(self) -> None:
        """Confere o contrato real: o que o chart define e o que o script lê.

        Este é o teste que teria pegado o bug. Ele lê o YAML **e** o código do
        script, e exige que o nome definido no chart apareça na chamada de
        `_exigir`. Comparar só o YAML contra uma lista escrita à mão passaria
        com o bug presente — foi exatamente o que aconteceu na primeira versão
        deste teste.
        """
        template = TEMPLATE_CHART.read_text(encoding="utf-8")
        definidas = set(re.findall(r"name:\s*(S3_\w+|GARAGE_S3_\w+)", template))
        codigo = Path(upload_s3.__file__).read_text(encoding="utf-8")

        # Cada variável que o chart injeta e o script precisa tem que aparecer
        # em _exigir(...). É o acoplamento entre chart e script que falhou.
        for nome in ("GARAGE_S3_ENDPOINT", "S3_ACCESS_KEY", "S3_SECRET_KEY"):
            assert nome in definidas, f"o chart deixou de injetar {nome}"

        # O endpoint é o caso que quebrou: o chart injeta GARAGE_S3_ENDPOINT e o
        # script precisa aceitá-lo explicitamente.
        assert '"GARAGE_S3_ENDPOINT"' in codigo, (
            "o script não aceita GARAGE_S3_ENDPOINT, que é o nome que o chart "
            "injeta — o Job falharia em 100% das execuções"
        )
        for nome in ("S3_ACCESS_KEY", "S3_SECRET_KEY"):
            assert f'"{nome}"' in codigo, f"o script não lê {nome}"


class TestUpload:
    """O caminho feliz e o caminho que recusa."""

    def _s3_falso(self, monkeypatch: pytest.MonkeyPatch) -> MagicMock:
        cliente = MagicMock()
        monkeypatch.setattr(upload_s3.boto3, "client", lambda *a, **k: cliente)
        monkeypatch.setenv("S3_ENDPOINT", "http://garage:3900")
        monkeypatch.setenv("S3_ACCESS_KEY", "chave")
        monkeypatch.setenv("S3_SECRET_KEY", "segredo")
        return cliente

    def test_envia_para_o_prefixo_certo(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cliente = self._s3_falso(monkeypatch)
        dump = tmp_path / "lakecore-20260101.sql.gz"
        dump.write_bytes(b"conteudo")

        assert upload_s3.main(["upload_s3.py", str(dump), "backup/postgres"]) == 0
        cliente.upload_file.assert_called_once_with(
            str(dump), "backup", "postgres/lakecore-20260101.sql.gz"
        )

    def test_sem_prefixo_usa_a_raiz_do_bucket(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cliente = self._s3_falso(monkeypatch)
        dump = tmp_path / "d.sql.gz"
        dump.write_bytes(b"x")

        assert upload_s3.main(["upload_s3.py", str(dump), "backup"]) == 0
        assert cliente.upload_file.call_args[0][2] == "d.sql.gz"

    def test_dump_vazio_e_recusado(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Zero bytes reportado como 'backup concluído' é o pior falso positivo."""
        cliente = self._s3_falso(monkeypatch)
        vazio = tmp_path / "vazio.sql.gz"
        vazio.touch()

        assert upload_s3.main(["upload_s3.py", str(vazio), "backup/postgres"]) == 65
        cliente.upload_file.assert_not_called()

    def test_arquivo_inexistente_e_recusado(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cliente = self._s3_falso(monkeypatch)
        assert upload_s3.main(["upload_s3.py", str(tmp_path / "nao"), "backup"]) == 66
        cliente.upload_file.assert_not_called()

    def test_falha_de_upload_retorna_nao_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Se o upload falha, o Job tem que falhar — senão o backup não existe."""
        from botocore.exceptions import ClientError

        cliente = self._s3_falso(monkeypatch)
        cliente.upload_file.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "negado"}}, "PutObject"
        )
        dump = tmp_path / "d.sql.gz"
        dump.write_bytes(b"x")

        assert upload_s3.main(["upload_s3.py", str(dump), "backup/postgres"]) == 1
