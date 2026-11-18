"""adiciona status ao catálogo

Revision ID: 8b1f2c3d4e5a
Revises: 65a942da6f86
Create Date: 2026-11-18 02:10:00

Segunda migração, criada de propósito para exercitar **evolução de schema com
dado dentro** — o caso que a primeira migração não testa, porque ela roda sempre
em banco vazio.

`server_default` é obrigatório aqui: a tabela já pode ter linhas quando esta
migração roda, e coluna `NOT NULL` sem default falharia em PostgreSQL com
"column contains null values". O default é removido depois da criação para que
o valor passe a vir do código, não do banco.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8b1f2c3d4e5a"
down_revision: str | None = "65a942da6f86"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUS = (
    "status in ('received','hashed','stored','cataloged','"
    "processing','done','failed')"
)


def upgrade() -> None:
    op.add_column(
        "objects",
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="cataloged",
        ),
    )
    # O `CHECK` entra depois do backfill implícito do server_default, senão
    # linhas antigas violariam a constraint no momento da criação.
    op.create_check_constraint("ck_objects_status_valido", "objects", _STATUS)
    op.create_index("ix_objects_status", "objects", ["status"])
    # Remove o default: daqui em diante o status vem do domínio, não do banco.
    op.alter_column("objects", "status", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_objects_status", table_name="objects")
    op.drop_constraint("ck_objects_status_valido", "objects", type_="check")
    op.drop_column("objects", "status")
