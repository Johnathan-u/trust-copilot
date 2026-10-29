#!/bin/sh
set -e
cd /app

# TC-03-001: validate the configuration contract first; production fails closed (exit 2) on
# missing/default/placeholder credentials or dev/demo switches. Only variable names are printed.
python -m app.core.config_contract check entrypoint

# Apply pending migrations before serving (avoids 500s when schema lags behind models).
# TC-03-002: migrations are additive only. This entrypoint applies the current
# head and never removes databases, schemas or volumes.
# Retry briefly when Postgres is still starting (docker compose).
i=0
while true; do
  if alembic upgrade head; then
    break
  fi
  i=$((i + 1))
  if [ "$i" -ge 15 ]; then
    echo "docker-entrypoint: alembic upgrade head failed after retries" >&2
    exit 1
  fi
  echo "docker-entrypoint: waiting for database (attempt $i/15)..." >&2
  sleep 2
done

exec "$@"
