"""Alembic environment.

Reads ``DATABASE_URL`` from environment. Alembic 1.14 still uses a sync
engine for migrations, so we swap ``+asyncpg`` for ``+psycopg2`` on the
fly. Models are imported eagerly so ``Base.metadata`` is populated.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from store import models  # noqa: F401  -- ensures models register with Base
from store.database import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _resolve_url() -> str:
    url = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg2://rasathane:rasathane@localhost:5435/rasathane",
    )
    if "+asyncpg" in url:
        url = url.replace("+asyncpg", "+psycopg2")
    return url


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting (for review/CI)."""
    context.configure(
        url=_resolve_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect and apply migrations."""
    cfg = config.get_section(config.config_ini_section) or {}
    cfg["sqlalchemy.url"] = _resolve_url()
    connectable = engine_from_config(cfg, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
