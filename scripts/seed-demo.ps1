# Seed demo workspace. Requires Postgres and MinIO (e.g. docker compose up -d postgres minio).
# Usage: .\scripts\seed-demo.ps1
$env:DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/trustcopilot"
$env:S3_ENDPOINT = "http://localhost:9000"
$env:S3_ACCESS_KEY = "minio"
$env:S3_SECRET_KEY = "minio123"
$env:S3_BUCKET_RAW = "trustcopilot-raw"
$env:S3_BUCKET_EXPORTS = "trustcopilot-exports"
Set-Location -Path "$PSScriptRoot\..\apps\api"
pip install -q -e .
python scripts/seed_demo_workspace.py
