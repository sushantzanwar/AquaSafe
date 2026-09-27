"""Engine and session factory. Persistence is optional: without DATABASE_URL the app runs as before."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from db.config import database_url

_engine: Engine | None = None
_factory: sessionmaker[Session] | None = None


def enabled() -> bool:
    return database_url() is not None


def get_engine() -> Engine:
    global _engine, _factory
    if _engine is None:
        url = database_url()
        if url is None:
            raise RuntimeError("DATABASE_URL is not set")
        # A short connect timeout: if the database is down, an analysis must not hang waiting for it.
        timeout = int(os.environ.get("DATABASE_CONNECT_TIMEOUT", "3") or 3)
        _engine = create_engine(url, pool_pre_ping=True, future=True, connect_args={"connect_timeout": timeout})
        _factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


@contextmanager
def session_scope() -> Iterator[Session]:
    """One transaction: commit on success, roll back on any error."""
    get_engine()
    assert _factory is not None
    session = _factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_connection() -> dict:
    """Connectivity and migration state, for startup logging and the health endpoint."""
    if not enabled():
        return {"enabled": False, "connected": False, "revision": None}
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
            try:
                revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
            except Exception:
                revision = None
        return {"enabled": True, "connected": True, "revision": revision}
    except Exception as exc:
        return {"enabled": True, "connected": False, "revision": None, "error": exc.__class__.__name__}


def reset_engine() -> None:
    """Drop the cached engine (used by tests that point DATABASE_URL at a fresh database)."""
    global _engine, _factory
    if _engine is not None:
        _engine.dispose()
    _engine, _factory = None, None
