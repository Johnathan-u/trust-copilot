# Stage: base (shared deps and app copy). Runtime deps come from the hashed lock (TC-02-002);
# dev/test tools (pytest, ruff) are in requirements-dev.lock and are not installed here.
FROM python:3.11-slim AS base
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
COPY apps/api/requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r /app/requirements.lock
COPY apps/api /app
RUN pip install --no-cache-dir --no-deps . \
    && pip check \
    && chmod +x /app/docker-entrypoint.sh \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --home-dir /tmp --shell /usr/sbin/nologin --no-create-home app \
    && chown -R app:app /app
USER app

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
