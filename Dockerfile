# Isolated Command Execution API — API and cleanup worker
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

COPY app/ ./app/

# Run as root so this container can access Docker socket to manage execution containers.
# Execution containers themselves run as UID 1000.

# Default: run API (override in compose for cleanup_worker)
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
