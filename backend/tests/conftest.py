"""Backend test setup: import path, and a throwaway PostgreSQL database per test session."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def _alembic_config(url: str):
    from alembic.config import Config

    config = Config(str(BACKEND / "alembic.ini"))
    config.attributes["url"] = url
    return config


@pytest.fixture(scope="session")
def pg_url():
    """A brand-new database on the DATABASE_URL server, migrated to head, dropped afterwards."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    from db.config import database_url

    base = database_url()
    if not base:
        pytest.skip("DATABASE_URL not set; start the db (docker compose up -d db) to run PostgreSQL tests")
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    name = f"aquasafe_test_{uuid.uuid4().hex[:10]}"
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
    except Exception as exc:
        pytest.skip(f"PostgreSQL not reachable: {exc.__class__.__name__}")
    url = make_url(base).set(database=name).render_as_string(hide_password=False)
    from alembic import command

    command.upgrade(_alembic_config(url), "head")
    yield url
    from db.session import reset_engine

    reset_engine()
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture
def db(pg_url, monkeypatch):
    """Point the app's session layer at the test database and give a clean slate per test."""
    from sqlalchemy import text

    from db.session import get_engine, reset_engine

    monkeypatch.setenv("DATABASE_URL", pg_url)
    reset_engine()
    engine = get_engine()
    with engine.begin() as connection:
        # TRUNCATE is not blocked by the append-only row triggers (they guard UPDATE/DELETE only).
        connection.execute(
            text(
                "TRUNCATE credit_transactions, reward_redemptions, rewards, field_submissions,"
                " water_body_analyses, water_bodies, users RESTART IDENTITY CASCADE"
            )
        )
    yield engine
    reset_engine()


@pytest.fixture
def alembic_config():
    return _alembic_config
