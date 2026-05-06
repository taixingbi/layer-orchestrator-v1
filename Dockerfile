FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

# System deps:
# - gcc/pkg-config/default-libmysqlclient-dev: for mysqlclient (if used)
# - curl: useful for container debugging/healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    pkg-config \
    default-libmysqlclient-dev \
    curl \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the whole app (safer than only one file)
COPY . .

EXPOSE 8000

# Optional healthcheck (FastAPI root may be 404; adjust if you have /health)
# HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
#   CMD curl -fsS "http://localhost:${PORT}/mcp/" >/dev/null || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
