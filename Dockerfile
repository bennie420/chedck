# ==============================================================================
# Stage 1: Build React / Vite Frontend
# ==============================================================================
FROM node:22-alpine AS ui-builder
WORKDIR /app/ui

# Install dependencies using package lock for reproducible builds
COPY ui/package*.json ./
RUN npm ci

# Build production assets
COPY ui/ ./
RUN npm run build

# ==============================================================================
# Stage 2: Production Python Runtime
# ==============================================================================
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

# Install system dependencies (curl for health check, fontconfig for font rendering)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    fontconfig \
    libfreetype6 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source, configurations, and assets
COPY src/ ./src/
COPY config/ ./config/
COPY fonts/ ./fonts/
COPY scripts/ ./scripts/
COPY buildspec.md ./

# Copy compiled static UI assets from builder stage
COPY --from=ui-builder /app/ui/dist ./ui/dist

# Ensure persistence directories exist
RUN mkdir -p /app/db /app/output /app/vault

# Expose unified port for UI + API
EXPOSE 8000

# Container healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/api/health || exit 1

# Start production server (supports cloud $PORT or default 8000)
CMD ["sh", "-c", "uvicorn api_server:app --host 0.0.0.0 --port ${PORT:-8000} --app-dir src"]
