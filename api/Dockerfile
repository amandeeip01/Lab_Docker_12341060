# Proximity Search API (FastAPI + NumPy)
FROM python:3.13-slim

# No .pyc files, unbuffered logs so `docker logs` shows output straight away
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    WORKERS=1 \
    LOG_LEVEL=info \
    LOCATIONS_CSV=/app/locations.csv \
    LINK_DIR=/data

WORKDIR /app

# Dependencies first, so this layer is cached when only the code changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py locations.csv ./

# Run as a normal user instead of root
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ[\"PORT\"]}/health', timeout=2)"

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port $PORT --workers $WORKERS --log-level $LOG_LEVEL"]
