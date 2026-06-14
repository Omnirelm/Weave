FROM python:3.11-slim AS builder

WORKDIR /app

# Copy only the files needed for installing dependencies
COPY pyproject.toml uv.lock README.md ./

# Install build dependencies and uv
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && curl -LsSf https://astral.sh/uv/install.sh | sh

# Add uv to PATH
ENV PATH="/root/.local/bin:/root/.cargo/bin:$PATH"

# uv sync installs only main dependencies (no dev extras) for smaller image
RUN uv sync --frozen --no-dev


# Final stage
FROM python:3.11-slim

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy application code
COPY src/ ./src/
COPY config.yaml ./
COPY agents/ ./agents/

# Create non-root user
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app
USER appuser

# Application port — override at runtime via REST_PORT env var
EXPOSE 9999

# -----------------------------------------------------------------------------
# Environment variables: pass at runtime via -e, --env-file, or compose env_file.
# Do not bake secrets into the image. Required: OPENAI_API_KEY.
# Optional: GITHUB_MCP_URL, MCP_SERVERS_CONFIG, REDIS_*, OTEL_*, etc.
# -----------------------------------------------------------------------------
ENV PYTHONPATH=/app
ENV REST_PORT=9999
ENV LOG_LEVEL=INFO

# OpenTelemetry (override OTEL_EXPORTER_OTLP_TRACES_ENDPOINT at runtime)
ENV OTEL_SERVICE_NAME=weave-orchestrator
ENV OTEL_ENABLED=true

# Health check via REST API
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request, os; port = os.environ.get('REST_PORT', '9999'); urllib.request.urlopen(f'http://localhost:{port}/health', timeout=5)" || exit 1

# Default command
CMD ["python", "src/main.py"]
