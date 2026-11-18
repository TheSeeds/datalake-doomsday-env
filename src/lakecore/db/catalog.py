"""Adaptador de `Catalog` sobre SQLAlchemy.

Implementa a porta do domínio (`lakecore.ports.Catalog`) sem que o domínio saiba
que SQL existe. Esta é a peça que a Onda 4 vai plugar no `ingest()`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from lakecore.db.models import ObjectRow
from lakecore.errors import DuplicateObjectError
from lakecore.models import Record


class SqlCatalog:
    """`Catalog` persistente.

    Recebe um `sessionmaker` em vez de uma `Session` pronta para que cada
    operação use sua própria transação: uma ingestão que falha no meio não deve
    deixar sessão suja para a próxima.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def add(self, record: Record) -> None:
        with self._session_factory() as session:
            linha = ObjectRow(
                sha256=record.sha256,
                bucket=record.bucket,
                key=record.key,
                size_bytes=record.size,
                content_type=record.content_type,
                origem=record.origem,
                tipo=record.tipo,
                coletado_em=record.coletado_em,
                criado_em=datetime.now(tz=UTC),
                metadados=record.metadados,
            )
            session.add(linha)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                # Distinguir duplicado de outros erros de integridade evita
                # transformar qualquer falha de constraint em "já existia".
                # A mensagem difere por dialeto, então a detecção precisa cobrir
                # os dois: PostgreSQL nomeia a constraint (`uq_objects_sha256`),
                # SQLite diz `UNIQUE constraint failed: objects.sha256`.
                if _e_violacao_de_sha_unico(exc):
                    raise DuplicateObjectError(record.sha256) from exc
                raise

    def by_sha256(self, sha256: str) -> Record | None:
        with self._session_factory() as session:
            linha = session.scalar(
                select(ObjectRow).where(ObjectRow.sha256 == sha256)
            )
            return _para_record(linha) if linha is not None else None

    def remover(self, sha256: str) -> bool:
        """Remove do catálogo. **Não** remove o objeto do storage.

        Existe para que a máquina de retenção (Onda 6) tenha uma operação
        explícita e testável, em vez de `DELETE` solto em SQL. Devolve `True` se
        algo foi removido.
        """
        with self._session_factory() as session:
            linha = session.scalar(select(ObjectRow).where(ObjectRow.sha256 == sha256))
            if linha is None:
                return False
            session.delete(linha)
            session.commit()
            return True


def _para_record(linha: ObjectRow) -> Record:
    return Record(
        sha256=linha.sha256,
        bucket=linha.bucket,
        key=linha.key,
        size=linha.size_bytes,
        content_type=linha.content_type,
        origem=linha.origem,
        tipo=linha.tipo,
        coletado_em=linha.coletado_em,
        metadados=linha.metadados,
    )


def _e_violacao_de_sha_unico(exc: IntegrityError) -> bool:
    """Reconhece a colisão de `sha256` em PostgreSQL e em SQLite.

    Centralizado e testado porque a mensagem é texto do driver: uma mudança de
    dialeto ou de versão do driver transformaria todo duplicado em erro genérico,
    e a ingestão deixaria de ser idempotente sem sinal claro.
    """
    texto = str(exc.orig).lower()

    if "uq_objects_sha256" in texto:
        return True

    return "sha256" in texto and (
        "unique constraint failed" in texto or "duplicate key" in texto
    )
