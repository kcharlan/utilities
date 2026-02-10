# Minimal, production-grade Python base
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

# System deps (curl is handy for local health checks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Python deps: prefer your requirements.txt if present at runtime; otherwise install Flask+Gunicorn
# We don't copy your app into the image because you'll bind-mount it at runtime.
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir gunicorn==23.0.0 && \
    pip install --no-cache-dir flask==3.1.2 || true

# Create a workspace where your host folder will be mounted
WORKDIR /workspace/llm_collector

# Expose the app port (informational)
EXPOSE 9000

# Default command assumes:
#  - your host volume is mounted at /workspace/llm_collector
#  - Python module path is the repo root, with app at collector/collector.py exposing `app`
# If you have a requirements.txt in the repo, we attempt to install it on container start.
CMD ["/bin/sh", "-lc", "\
    if [ -f requirements.txt ]; then \
      pip install --no-cache-dir -r requirements.txt || true; \
    elif [ -f collector/requirements.txt ]; then \
      pip install --no-cache-dir -r collector/requirements.txt || true; \
    fi; \
    mkdir -p snapshots; \
    exec gunicorn \
      --chdir /workspace/llm_collector \
      --workers 1 \
      --bind 0.0.0.0:9000 \
      --timeout 120 \
      --access-logfile - \
      --error-logfile - \
      collector.collector:app \
  "]
