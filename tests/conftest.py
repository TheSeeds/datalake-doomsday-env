"""Configuração comum dos testes.

`src/` é adicionado ao `sys.path` porque o projeto não é instalado como pacote
nesta fase — evita um `pip install -e` obrigatório para rodar `make test`.
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
