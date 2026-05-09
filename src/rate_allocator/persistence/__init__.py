"""Persistence layer: SCD2 schema, ingestion, and session management."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from rate_allocator.persistence.models import Base

DEFAULT_DB_FILE = Path(__file__).resolve().parents[3] / "data" / "rates.db"
DB_URL_ENV = "RATE_ALLOCATOR_DB_URL"


def get_database_url() -> str:
    """Resolve the DB URL from env or fall back to a local SQLite file."""
    return os.environ.get(DB_URL_ENV, f"sqlite:///{DEFAULT_DB_FILE}")


def create_db_engine(url: str | None = None, *, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine for the given URL (or the env-resolved default)."""
    resolved = url or get_database_url()
    connect_args: dict = {}
    if resolved.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(resolved, echo=echo, future=True, connect_args=connect_args)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Build a session factory bound to the engine."""
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_schema(engine: Engine) -> None:
    """Create all tables and indexes defined on the metadata.

    Useful for tests and first-run bootstrapping. Production deployments should
    prefer Alembic migrations; this is idempotent and safe to call alongside.
    """
    Base.metadata.create_all(engine)


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Yield a session, committing on success and rolling back on error."""
    factory = create_session_factory(engine)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


__all__ = [
    "Base",
    "DB_URL_ENV",
    "DEFAULT_DB_FILE",
    "create_db_engine",
    "create_session_factory",
    "get_database_url",
    "init_schema",
    "session_scope",
]
