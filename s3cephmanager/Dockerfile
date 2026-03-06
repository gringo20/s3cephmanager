# ── Build stage ────────────────────────────────────────────────────────────────
FROM python:3.13-slim AS builder

WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --prefix=/install --no-cache-dir -r requirements.txt

# ── Runtime stage ──────────────────────────────────────────────────────────────
FROM python:3.13-slim AS runtime

LABEL org.opencontainers.image.title="CephS3Manager-Web"
LABEL org.opencontainers.image.description="Modern S3 + Ceph RGW admin tool"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    APP_HOST=0.0.0.0 \
    APP_PORT=8080

WORKDIR /app

COPY --from=builder /install /usr/local
COPY . .

RUN mkdir -p /data /app/.nicegui && \
    addgroup --system appgroup && \
    adduser  --system --ingroup appgroup appuser && \
    chown -R appuser:appgroup /app /data

USER appuser
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/')"

CMD ["python", "main.py"]
