# ── Build stage ───────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt


# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Install Playwright's own system dependencies (version-aware, covers libXfixes and all others)
# --with-deps is the only reliable way to get the full Chromium dependency tree on Debian/slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Pin browser install location so it survives any env var differences at runtime
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Install Chromium + ALL required system libraries in one go
RUN playwright install --with-deps chromium

# Copy application code
COPY . .

# Create export directory
RUN mkdir -p /app/exports

EXPOSE 9000

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-9000}"]
