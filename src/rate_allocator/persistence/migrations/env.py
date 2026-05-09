"""Alembic environment for the rate-allocator persistence layer.

The DB URL is resolved at runtime from ``RATE_ALLOCATOR_DB_URL`` (or the local
SQLite default) rather than being baked into ``alembic.ini``, so migrations
work the same way locally and in any deployed environment.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from rate_allocator.persistence import get_database_url
from rate_allocator.persistence.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Honor an explicit URL passed in by the embedding code (e.g. tests calling
# Config.set_main_option(...)). Only fall back to the env-resolved default
# when the config has no URL configured.
_existing_url = config.get_main_option("sqlalchemy.url")
if not _existing_url:
    config.set_main_option("sqlalchemy.url", get_database_url())

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generate SQL without a live connection."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=url.startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations against a live engine."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        is_sqlite = connection.dialect.name == "sqlite"
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=is_sqlite,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
