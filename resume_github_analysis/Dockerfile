# ── Build stage ───────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt


# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim

# Create a non-root user for security
RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application source (excluding files listed in .dockerignore)
COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 7860

# AWS credentials and GitHub token must be supplied at runtime via environment variables:
#   docker run -e AWS_ACCESS_KEY_ID=... -e AWS_SECRET_ACCESS_KEY=... \
#              -e AWS_DEFAULT_REGION=us-east-1 -e GITHUB_TOKEN=... ...
# Or use --env-file .env (keep .env out of the image — it is listed in .dockerignore)

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
