# Run migrations. Requires Docker Postgres or local Postgres on port 5432.
# Usage: .\scripts\run-migrations.ps1
# Or with docker: docker compose up -d postgres minio; .\scripts\run-migrations.ps1
$env:DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/trustcopilot"
Set-Location -Path "$PSScriptRoot\..\apps\api"
pip install -q alembic sqlalchemy psycopg2-binary
alembic upgrade head
