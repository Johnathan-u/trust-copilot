# Run full API test suite (including Trust Center and auth tests).
# Requires Postgres running (e.g. docker compose up -d postgres).
# The app DB is "trustcopilot"; the test DB "trustcopilot_test" is created by
# infra/postgres/init-create-test-db.sh when the Postgres container is first created.
# If you already had Postgres running before adding that init, create the test DB once:
#   docker exec -it trust-copilot-postgres psql -U postgres -d trustcopilot -c "CREATE DATABASE trustcopilot_test;"
# Usage: .\scripts\run-api-tests.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$api = Join-Path $root "apps\api"

$env:DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/trustcopilot_test"
$env:SESSION_SECRET = "test-secret"

Set-Location $api
Write-Host "Running migrations on test DB..." -ForegroundColor Cyan
& alembic upgrade head
if ($LASTEXITCODE -ne 0) {
    Write-Host "Migrations failed. Is Postgres running? (e.g. docker compose up -d postgres)" -ForegroundColor Red
    exit $LASTEXITCODE
}
Write-Host "Running pytest..." -ForegroundColor Cyan
& python -m pytest tests/ -v --tb=short
exit $LASTEXITCODE
