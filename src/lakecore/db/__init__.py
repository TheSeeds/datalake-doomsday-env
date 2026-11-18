"""Pacote de persistência.

Separado de `lakecore` raiz por uma razão de arquitetura: o domínio não importa
SQLAlchemy (ADR-007). Este pacote é o adaptador que **implementa** as portas do
domínio — quem quiser o domínio puro não carrega dependência nenhuma.
"""

from __future__ import annotations

from lakecore.db.models import Base, ObjectRow, UploadRow

__all__ = ["Base", "ObjectRow", "UploadRow"]
