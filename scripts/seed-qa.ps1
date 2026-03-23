# Seed QA test data for docs/QA_TEST_SHEET.md.
# Requires Postgres (and optional MinIO for document storage).
# Usage: .\scripts\seed-qa.ps1

$env:DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/trustcopilot"
$env:S3_ENDPOINT = "http://localhost:9000"
$env:S3_ACCESS_KEY = "minio"
$env:S3_SECRET_KEY = "minio123"
$env:S3_BUCKET_RAW = "trustcopilot-raw"
$env:S3_BUCKET_EXPORTS = "trustcopilot-exports"

$apiDir = Join-Path (Join-Path $PSScriptRoot "..") "apps\api"
Set-Location -Path $apiDir

# Ensure package is installed so app imports resolve
pip install -q -e . 2>$null

python scripts/seed_qa_test_data.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Next: Start the stack (Postgres, API, worker, frontend) and run the QA pass from docs/QA_TEST_SHEET.md."
