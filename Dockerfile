# Multi-stage build for TG_parser
# v1.2: Docker support with Multi-LLM

# Builder stage
FROM python:3.12-slim AS builder

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Production stage
FROM python:3.12-slim

WORKDIR /app

# Copy dependencies from builder
COPY --from=builder /root/.local /root/.local

# Set PATH to include pip user packages
ENV PATH=/root/.local/bin:$PATH

# Copy application code
COPY tg_parser/ ./tg_parser/
COPY prompts/ ./prompts/
COPY pyproject.toml .
COPY README.md .

# Install package in editable mode
RUN pip install --no-cache-dir -e .

# Create data directory for SQLite databases
RUN mkdir -p /app/data

# Default environment variables
ENV PYTHONUNBUFFERED=1

# Set default command
ENTRYPOINT ["python", "-m", "tg_parser.cli"]
CMD ["--help"]

