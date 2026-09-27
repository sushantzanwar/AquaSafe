"""Database configuration. The only input is DATABASE_URL; nothing is hard-coded."""

from __future__ import annotations

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent


def _load_env_files() -> None:
    """Fill missing variables from repo-root .env and backend/.env. Real env vars always win."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    for path in (REPO_ROOT / ".env", BACKEND_DIR / ".env"):
        if path.is_file():
            load_dotenv(path, override=False)


_load_env_files()


def database_url() -> str | None:
    """SQLAlchemy URL, normalised to the psycopg (v3) driver. None means persistence is disabled."""
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        return None
    # Hosted providers (Render, Heroku, Neon) hand out postgres:// or postgresql:// URLs.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def uploads_dir() -> Path:
    """Root for locally stored submission images (see db/storage.py)."""
    configured = (os.environ.get("AQUASAFE_UPLOADS_DIR") or "").strip()
    return Path(configured) if configured else REPO_ROOT / "data" / "uploads"
