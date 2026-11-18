"""Modelo de dados do catálogo.

O catálogo é o produto: ele transforma bytes opacos em acervo pesquisável. O
schema precisa sustentar três invariantes que o domínio já assume:

1. **`sha256` é único** — é a chave de idempotência. Sem isso, "rodar duas vezes"
   deixa de ser seguro e a Onda 4 não tem como cumprir o critério.
2. **Proveniência obrigatória** — `origem` é `NOT NULL`. Dado sem procedência
   não entra.
3. **`metadados` é flexível** — JSONB, porque o lake aceita dado heterogêneo e
   não pode impor schema rígido na entrada.

Multi-dialeto é requisito real, não zelo: os testes rodam em SQLite em memória
(milissegundos, sem container) e o CI roda em PostgreSQL. Tipos são escolhidos
para que **o mesmo `CREATE TABLE` funcione nos dois**.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON, TypeDecorator

#: Convenção de nomes explícita. Sem ela, o nome de constraint gerado varia por
#: dialeto e o `downgrade` da migração quebra em um dos dois.
CONVENCAO = MetaData(
    naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)


class JSONBMaisPortavel(TypeDecorator[dict[str, Any]]):
    """JSONB no PostgreSQL, JSON no restante.

    `JSONB` dá índice e operadores, mas não existe em SQLite. Manter os dois
    evita que o teste rode em um schema e a produção em outro — a divergência
    mais cara de detectar tarde.
    """

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


class Base(DeclarativeBase):
    metadata = CONVENCAO


class ObjectRow(Base):
    """Linha de um objeto bruto preservado.

    Nome da tabela no plural (`objects`) porque ela guarda N objetos; a classe
    usa `Row` para deixar claro que é registro de persistência, não a entidade
    de domínio (`lakecore.Record`).
    """

    __tablename__ = "objects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    bucket: Mapped[str] = mapped_column(String(63), nullable=False)
    key: Mapped[str] = mapped_column(Text, nullable=False)

    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)

    origem: Mapped[str] = mapped_column(String(255), nullable=False)
    tipo: Mapped[str] = mapped_column(String(64), nullable=False)
    coletado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    metadados: Mapped[dict[str, Any]] = mapped_column(
        JSONBMaisPortavel, nullable=False, default=dict
    )
    # Estado da máquina de estados do domínio (`UploadState`). Persistido porque
    # a Onda 4 precisa responder "o que entrou mas não terminou de processar" —
    # sem isso, um Job interrompido deixa objeto órfão e ninguém sabe.
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="cataloged"
    )

    __table_args__ = (
        UniqueConstraint("sha256", name="uq_objects_sha256"),
        CheckConstraint("size_bytes >= 0", name="size_nao_negativo"),
        CheckConstraint("length(sha256) = 64", name="sha256_com_64_caracteres"),
        CheckConstraint(
            "status in ('received','hashed','stored','cataloged','processing','done','failed')",
            name="status_valido",
        ),
        Index("ix_objects_origem_coletado_em", "origem", "coletado_em"),
        Index("ix_objects_tipo", "tipo"),
        Index("ix_objects_status", "status"),
    )


class UploadRow(Base):
    """Lote de ingestão.

    Um `drop/` processado, um `POST /uploads`, um `push` — cada um vira uma
    linha. Serve para responder "o que entrou e quando", que é a primeira
    pergunta operacional de qualquer lake.
    """

    __tablename__ = "uploads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    origem: Mapped[str] = mapped_column(String(255), nullable=False)
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    aceitos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicados: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    falhas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    iniciado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    concluido_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    erro: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("total >= 0", name="total_nao_negativo"),
        CheckConstraint("aceitos >= 0", name="aceitos_nao_negativo"),
        CheckConstraint("duplicados >= 0", name="duplicados_nao_negativo"),
        CheckConstraint("falhas >= 0", name="falhas_nao_negativo"),
        Index("ix_uploads_origem_iniciado_em", "origem", "iniciado_em"),
    )


class SaudeRow(Base):
    """Sinal de frescor: quando cada rotina deu certo pela última vez.

    POR QUE ESTA TABELA EXISTE:

    em 2026-11-18 o CronJob de backup falhava em 100% das execuções havia horas
    e ninguém viu. A informação estava visível em `kubectl get jobs` — o que
    faltava era uma resposta pronta para a pergunta que alguém realmente faz:
    "meu backup está funcionando?".

    Um painel responde tendência, e tendência exige alguém olhando. Esta tabela
    responde o **estado**, e responde com a stack de observabilidade desligada.

    `ultimo_sucesso` e `ultima_falha` são colunas separadas de propósito: um
    backup que falhou ontem e funcionou hoje é diferente de um que nunca
    funcionou. Um booleano `ok` achataria os dois, e o primeiro é o caso normal.
    """

    __tablename__ = "saude"

    #: Nome do sinal (`backup`, `ingestao`, `export`). Chave natural: é por ele
    #: que se pergunta, e um `id` surrogate só adicionaria um join.
    sinal: Mapped[str] = mapped_column(String(64), primary_key=True)

    ultimo_sucesso: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ultima_falha: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    total_ok: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_falha: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    #: Mensagem da última falha. Guardar só "failed" obrigaria a caçar o log de
    #: um pod que o Job já apagou — foi exatamente o que aconteceu no incidente.
    detalhe: Mapped[str | None] = mapped_column(Text, nullable=True)

    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
