#!/bin/bash
# Create test DB for pytest (scripts/run-api-tests.ps1).
# Runs when Postgres container is first initialized (docker-entrypoint-initdb.d).
set -e
if [ "$(psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT 1 FROM pg_database WHERE datname = 'trustcopilot_test'")" != "1" ]; then
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" -d "$POSTGRES_DB" -c "CREATE DATABASE trustcopilot_test";
fi
