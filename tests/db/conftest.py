"""Fixtures compartilhadas dos testes de banco.

Duas famílias:

- **Engine de teste** (`engine`, `session_factory`): SQLite em memória por padrão,
  PostgreSQL real quando `LAKECORE_TEST_PG_URL` está definida. Schema criado por
  `metadata.create_all` — estes testes exercitam o catálogo, não a migração.
- **Schema dedicado** (`url_schema_dedicado`, `aplicar_migracao`): cada teste de
  migração ganha um schema próprio no PostgreSQL, criado e destruído em volta do
  caso. Permite exercitar `downgrade` sem tocar em banco de desenvolvimento.

Regra herdada do geoflow: **migração testada só em banco novo não é testada.**
Só faz sentido com PostgreSQL de verdade — SQLite não tem `ALTER COLUMN`,
`JSONB` nem `GIN`.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from lakecore.db.models import Base


@pytest.fixture(scope="session")
def pg_url() -> str | None:
    return os.environ.get("LAKECORE_TEST_PG_URL")


@pytest.fixture
def engine(pg_url: str | None) -> Iterator[Engine]:
    if pg_url:
        eng = create_engine(pg_url, future=True)
        Base.metadata.drop_all(eng)
        Base.metadata.create_all(eng)
    else:
        eng = create_engine(
            "sqlite+pysqlite:///:memory:",
            future=True,
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(eng)

    try:
        yield eng
    finally:
        if pg_url:
            Base.metadata.drop_all(eng)
        eng.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def url_schema_dedicado(pg_url: str | None) -> Iterator[tuple[str, Engine]]:
    """Schema exclusivo no PostgreSQL, com `search_path` apontando para ele."""
    if not pg_url:
        pytest.skip("exige PostgreSQL real (LAKECORE_TEST_PG_URL)")

    schema = f"t_{uuid.uuid4().hex[:12]}"
    admin = create_engine(pg_url, future=True)

    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))

    # `%` precisa vir escapado: o `alembic.ini` é lido pelo configparser, que
    # interpola `%` e quebra com "invalid interpolation syntax".
    url = f"{pg_url}?options=-csearch_path%3D{schema}"
    url_escapada = url.replace("%", "%%")
    engine = create_engine(url, future=True)

    try:
        yield url_escapada, engine
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def aplicar_migracao(
    url_schema_dedicado: tuple[str, Engine], monkeypatch: pytest.MonkeyPatch
) -> Callable[[str], None]:
    """Aplica uma revisão do Alembic no schema dedicado."""
    url, _engine = url_schema_dedicado
    monkeypatch.setenv("LAKECORE_DATABASE_URL", url)

    def _aplicar(revisao: str) -> None:
        cfg = Config("alembic.ini")
        cfg.set_main_option("script_location", "src/lakecore/db/migrations")
        cfg.set_main_option("sqlalchemy.url", url)
        command.upgrade(cfg, revisao)

    return _aplicar
