"""Permite `python -m lakecore.mcp`, que é como a tela inicia o servidor.

Sem este arquivo, `python -m lakecore.mcp` falha com "is a package and cannot be
directly executed" — era exatamente o erro que deixava a tela pendurada
esperando um servidor que nunca subia.
"""

from __future__ import annotations

from lakecore.mcp import main

if __name__ == "__main__":
    main()
