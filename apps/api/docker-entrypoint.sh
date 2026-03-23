#!/bin/sh
set -e
cd /app

# Apply pending migrations before serving (avoids 500s when schema lags behind models).
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
