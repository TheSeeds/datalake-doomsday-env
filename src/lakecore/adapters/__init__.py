"""Adaptadores de infraestrutura para as portas do domínio.

Separados de `lakecore` raiz por ADR-007: o domínio não carrega SDK de nuvem. Quem
quer o domínio puro importa `lakecore`; quem quer o lake funcionando importa
`lakecore.adapters`.
"""

from __future__ import annotations

__all__ = ["s3_store"]
