"""catalogo inicial: objects e uploads

Revision ID: 65a942da6f86
Revises:
Create Date: 2026-11-18 01:32:21.132763

Notas de portabilidade (custaram iteração para acertar):

- `JSONB` só existe no PostgreSQL. Uso `sa.JSON().with_variant(JSONB, "postgresql")`
  para que o MESMO arquivo rode nos dois dialetos. A versão autogerada
  referenciava `lakecore.db.models.JSONBMaisPortavel()` sem importá-la — nome
  indisponível em tempo de execução, migração quebraria com `NameError`.
- Índice GIN em `metadados` é criado **apenas** em PostgreSQL: em SQLite ele não
  existe e a tentativa derrubaria a migração inteira.
- `downgrade` é funcional e reversível de verdade. Migração sem `downgrade` não
  pode ser testada, e migração não testada é migração que falha em produção.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "65a942da6f86"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "objects",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("bucket", sa.String(length=63), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("origem", sa.String(length=255), nullable=False),
        sa.Column("tipo", sa.String(length=64), nullable=False),
        sa.Column("coletado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadados", _JSON, nullable=False),
        sa.CheckConstraint(
            "length(sha256) = 64", name=op.f("ck_objects_sha256_com_64_caracteres")
        ),
        sa.CheckConstraint(
            "size_bytes >= 0", name=op.f("ck_objects_size_nao_negativo")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_objects")),
        sa.UniqueConstraint("sha256", name="uq_objects_sha256"),
    )
    op.create_index(
        "ix_objects_origem_coletado_em", "objects", ["origem", "coletado_em"]
    )
    op.create_index("ix_objects_tipo", "objects", ["tipo"])

    op.create_table(
        "uploads",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("origem", sa.String(length=255), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("aceitos", sa.Integer(), nullable=False),
        sa.Column("duplicados", sa.Integer(), nullable=False),
        sa.Column("falhas", sa.Integer(), nullable=False),
        sa.Column("iniciado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("concluido_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("erro", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "total >= 0", name=op.f("ck_uploads_total_nao_negativo")
        ),
        sa.CheckConstraint(
            "aceitos >= 0", name=op.f("ck_uploads_aceitos_nao_negativo")
        ),
        sa.CheckConstraint(
            "duplicados >= 0", name=op.f("ck_uploads_duplicados_nao_negativo")
        ),
        sa.CheckConstraint(
            "falhas >= 0", name=op.f("ck_uploads_falhas_nao_negativo")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_uploads")),
    )
    op.create_index(
        "ix_uploads_origem_iniciado_em", "uploads", ["origem", "iniciado_em"]
    )

    # GIN só faz sentido (e só existe) em PostgreSQL.
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX ix_objects_metadados_gin ON objects USING gin (metadados)"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_objects_metadados_gin")

    op.drop_index("ix_uploads_origem_iniciado_em", table_name="uploads")
    op.drop_table("uploads")

    op.drop_index("ix_objects_tipo", table_name="objects")
    op.drop_index("ix_objects_origem_coletado_em", table_name="objects")
    op.drop_table("objects")
