"""Configuração de execução das migrações.

A URL do banco vem de `LAKECORE_DATABASE_URL`, nunca do `alembic.ini`. Isso
mantém credencial fora do repositório (M2.3 do projeto, ADR-009) e permite que o
mesmo arquivo rode em SQLite nos testes e em PostgreSQL no cluster.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from lakecore.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

url = os.environ.get("LAKECORE_DATABASE_URL")
if not url:
    raise SystemExit(
        "LAKECORE_DATABASE_URL não definida. Ex.: "
        "postgresql+psycopg://datalake:senha@localhost:5432/datalake"
    )

config.set_main_option("sqlalchemy.url", url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Gera SQL sem conectar — útil para revisar o que será aplicado."""
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            # SQLite não suporta ALTER COLUMN; batch mode reescreve a tabela.
            # Necessário para que `downgrade` funcione nos dois dialetos.
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
