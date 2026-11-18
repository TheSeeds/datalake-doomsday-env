"""Valida as definições de módulo.

POR QUE ISTO EXISTE:

o formato de `module.yaml` está especificado na §7 da arquitetura desde a Onda 0
e nunca foi exercitado — o `modules/` estava vazio. Um formato que ninguém lê é
um formato que não existe: o primeiro módulo escrito contra ele seria também o
primeiro a descobrir que ele está incompleto.

Estes testes são o "leitor" do formato. Eles exigem os campos que a arquitetura
promete, e exigem o que as lições operacionais deste projeto mostraram ser
necessário — como `images`, que só ficou claro na Onda 6, quando um backup
falhou por imagem ausente no containerd.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

MODULES = Path(__file__).resolve().parents[1] / "modules"

#: Campos que a §7 promete. Faltar qualquer um significa que a arquitetura
#: descreve um módulo que o código não sabe instalar.
OBRIGATORIOS = ("name", "version", "requires", "provides", "install", "uninstall")


def modulos() -> list[Path]:
    """Todo `module.yaml` sob `modules/`, exceto o `.gitkeep`."""
    return sorted(MODULES.glob("*/module.yaml"))


def carregar(caminho: Path) -> dict[str, Any]:
    dados = yaml.safe_load(caminho.read_text(encoding="utf-8"))
    assert isinstance(dados, dict), f"{caminho} não é um mapa YAML"
    return dados


def test_existe_pelo_menos_um_modulo() -> None:
    """O módulo de observabilidade é o primeiro; se sumir, o formato volta a
    ser teoria."""
    assert modulos(), "nenhum module.yaml encontrado"


@pytest.mark.parametrize("caminho", modulos(), ids=lambda p: p.parent.name)
class TestFormato:
    def test_tem_os_campos_obrigatorios(self, caminho: Path) -> None:
        dados = carregar(caminho)
        faltando = [c for c in OBRIGATORIOS if c not in dados]
        assert not faltando, f"{caminho.parent.name} sem {faltando}"

    def test_name_bate_com_o_diretorio(self, caminho: Path) -> None:
        """O diretório é a identidade do módulo; divergir confunde o install."""
        assert carregar(caminho)["name"] == caminho.parent.name

    def test_version_semver(self, caminho: Path) -> None:
        versao = str(carregar(caminho)["version"])
        partes = versao.split(".")
        assert len(partes) == 3 and all(p.isdigit() for p in partes), (
            f"versão {versao!r} não é MAJOR.MINOR.PATCH"
        )

    def test_requires_declara_os_tres_recursos(self, caminho: Path) -> None:
        """`gpu`, `ram` e `disk` são o que decide se o módulo cabe. Omitir um
        deles faz o `install.sh` aceitar um módulo que não roda."""
        requires = carregar(caminho)["requires"]
        for recurso in ("gpu", "ram", "disk"):
            assert recurso in requires, f"{caminho.parent.name} não declara {recurso}"

    def test_gpu_e_none_optional_ou_required(self, caminho: Path) -> None:
        valor = carregar(caminho)["requires"]["gpu"]
        assert valor in ("none", "optional", "required"), (
            f"gpu={valor!r}: o instalador não sabe interpretar isso"
        )

    def test_uninstall_declara_keeps(self, caminho: Path) -> None:
        """A regra herdada do NOMAD: desinstalar não apaga dado do usuário.

        `keeps` é obrigatório e pode ser lista vazia — mas tem que ser uma
        decisão escrita, não um esquecimento.
        """
        uninstall = carregar(caminho)["uninstall"]
        assert "keeps" in uninstall, (
            f"{caminho.parent.name}: sem 'keeps', remover o módulo apagaria dado "
            "do usuário por omissão"
        )
        assert isinstance(uninstall["keeps"], list)

    def test_images_declaradas_quando_ha_chart(self, caminho: Path) -> None:
        """Com `imagePullPolicy: Never`, imagem não declarada é instalação que
        falha no primeiro pod — a lição da Onda 6."""
        dados = carregar(caminho)
        instalar = dados.get("install", {})
        if not instalar.get("charts"):
            pytest.skip("módulo sem charts")
        assert instalar.get("images"), (
            f"{caminho.parent.name}: chart sem lista de `images` vai falhar no "
            "airgap, onde o kubelet não pode baixar nada"
        )

    def test_charts_sao_vendorizados(self, caminho: Path) -> None:
        """`--repo` na instalação baixaria da internet e quebra o airgap."""
        for chart in carregar(caminho)["install"]["charts"]:
            assert "source" in chart, f"chart {chart.get('name')} sem source"
            assert chart["source"].startswith("vendor/"), (
                f"chart {chart['name']}: source {chart['source']!r} não é vendor/"
            )
