# =========================
# Build stage
# =========================
FROM python:3.12-slim AS builder

WORKDIR /app

# Install uv
RUN pip install --no-cache-dir uv

# Enable project-local virtualenv
ENV UV_PROJECT_ENVIRONMENT=/app/.venv

# Copy dependency files first for Docker layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-dev

# Copy source code
COPY . .

# =========================
# Runtime stage
# =========================
FROM python:3.12-slim

WORKDIR /app

# Copy application + virtualenv
COPY --from=builder /app /app

# Use venv binaries
ENV PATH="/app/.venv/bin:$PATH"

# Recommended for Docker logs
ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]