# AquaSafe: FastAPI backend + static frontend in one image.
# Used by docker compose (with the `db` service) and by Render (see render.yaml / DEPLOYMENT.md).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PORT=8000

# curl: healthcheck. OpenCV is the headless build, so no libgl/glib are needed.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 aquasafe

WORKDIR /app
COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

# Same layout as the repo: db/config.py resolves the repo root as the parent of backend/.
COPY backend ./backend
COPY ai_assistant ./ai_assistant
COPY config ./config
COPY data ./data
COPY frontend ./frontend

# Writable state (uploaded photos, legacy SQLite history). Mount volumes here to keep it across restarts.
ENV AQUASAFE_UPLOADS_DIR=/data/uploads AQUASAFE_LEGACY_DB=/data/historical_data.db
# Named volumes inherit this ownership on first use, so the non-root user can write to them.
RUN mkdir -p /data /app/data/uploads && chown -R aquasafe:aquasafe /data /app/data
USER aquasafe

WORKDIR /app/backend
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=10 \
    CMD curl -fs "http://localhost:${PORT:-8000}/api/health/db" || exit 1

# Migrate when a database is configured (the credit features need it; everything else runs without),
# then serve on $PORT (Render assigns it; default 8000).
CMD ["sh", "-c", "if [ -n \"$DATABASE_URL\" ]; then alembic upgrade head; fi && exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
