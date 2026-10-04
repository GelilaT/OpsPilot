# One image for both the api and the worker service (SRS 2.1); the command selects the role.
FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PYTHONPATH=/app
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install . && pip uninstall -y opspilot-api
COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
COPY fixtures ./fixtures
RUN useradd --uid 10001 --no-create-home opspilot
USER opspilot
EXPOSE 8080
# api (default):   uvicorn on :8080 (Cloud Run)
# worker:          procrastinate --app=app.workers.app.app worker
# migrate:         alembic upgrade head
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips='*'"]
