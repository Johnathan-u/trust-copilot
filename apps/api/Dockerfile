# Stage: base (shared deps and app copy). Deps from pyproject.toml to avoid drift.
FROM python:3.11-slim AS base
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
COPY apps/api /app
RUN pip install --no-cache-dir . \
    && chmod +x /app/docker-entrypoint.sh

# Stage: production (no reload, with healthcheck)
FROM base AS production
EXPOSE 8000
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
# Role-aware probe (TC-03-003): TC_PROCESS_ROLE=api (default) -> GET /healthz on loopback;
# TC_PROCESS_ROLE=worker -> heartbeat-file freshness, never HTTP. Compose also passes the role explicitly.
ENV TC_PROCESS_ROLE=api
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -m app.probe || exit 1

# Stage: dev (default target for local docker compose; with reload, no healthcheck)
FROM base AS dev
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
