# AquaSafe Production Dockerfile for Render / Cloud Deployment
FROM python:3.11-slim

# Prevent python from writing pyc files and buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

# Install system dependencies for OpenCV, Shapely and image processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libglib2.0-0 \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency definition
COPY requirements.txt /app/requirements.txt

# Install python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy all application directories
COPY backend /app/backend
COPY frontend /app/frontend
COPY ai_assistant /app/ai_assistant
COPY config /app/config
COPY data /app/data

# Ensure backend directory is in PYTHONPATH
ENV PYTHONPATH=/app:/app/backend:/app/ai_assistant

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:' + str(os.environ.get('PORT', 8000)) + '/api/water-bodies')" || exit 1

# Start FastAPI server on dynamic $PORT assigned by Render
WORKDIR /app/backend
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
