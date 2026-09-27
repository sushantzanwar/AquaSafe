# AquaSafe: FastAPI backend + static frontend in one image (served on :8000).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1

# curl: healthcheck. libgl/glib are not needed (opencv-python-headless).
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 aquasafe

WORKDIR /app
COPY requirements.docker.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

# Same layout as the repo: db/config.py resolves the repo root as the parent of backend/.
COPY backend ./backend
COPY ai_assistant ./ai_assistant
COPY config ./config
COPY data ./data
COPY frontend ./frontend

# Writable state (uploaded photos, legacy SQLite history) lives on a volume, not in the image.
ENV AQUASAFE_UPLOADS_DIR=/data/uploads AQUASAFE_LEGACY_DB=/data/historical_data.db
# Named volumes inherit this ownership on first use, so the non-root user can write to them.
RUN mkdir -p /data /app/data/uploads && chown -R aquasafe:aquasafe /data /app/data
USER aquasafe

WORKDIR /app/backend
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=10 \
    CMD curl -fs http://localhost:8000/api/health/db || exit 1
# Apply migrations, then serve. (db is healthy before this starts; see docker-compose.yml.)
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn main:app --host 0.0.0.0 --port 8000"]
