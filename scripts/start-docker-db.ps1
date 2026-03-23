# Restore Docker access and start Postgres + MinIO, then run migrations and seed.
# Run from repo root: .\scripts\start-docker-db.ps1
# Prerequisite: Docker Desktop installed. If it is not running, this script will try to start it.

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

# Step 1 & 2 — Ensure Docker daemon is reachable
Write-Host "Checking Docker..." -ForegroundColor Cyan
$dockerOk = $false
foreach ($i in 1..30) {
    $err = $null
    docker info 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { $dockerOk = $true; break }
    if ($i -eq 1) {
        Write-Host "Docker daemon not ready. Attempting to start Docker Desktop..."
        Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe" -ErrorAction SilentlyContinue
    }
    Write-Host "  Waiting for Docker... ($i/30)"
    Start-Sleep -Seconds 3
}
if (-not $dockerOk) {
    Write-Host "Docker did not become available. Start Docker Desktop manually, then run:" -ForegroundColor Yellow
    Write-Host "  cd '$repoRoot'; docker compose up -d postgres minio; .\scripts\run-migrations.ps1; .\scripts\seed-demo.ps1" -ForegroundColor White
    exit 1
}
Write-Host "Docker is ready." -ForegroundColor Green

# Step 3 & 4 — Start Postgres and MinIO
Set-Location $repoRoot
Write-Host "Starting Postgres and MinIO..." -ForegroundColor Cyan
docker compose up -d postgres minio
if ($LASTEXITCODE -ne 0) { exit 1 }
Write-Host "Containers started. Giving Postgres a few seconds to accept connections..." -ForegroundColor Cyan
Start-Sleep -Seconds 5

# Step 5 — Migrations
Write-Host "Running migrations..." -ForegroundColor Cyan
& "$PSScriptRoot\run-migrations.ps1"
if ($LASTEXITCODE -ne 0) { exit 1 }

# Step 6 — Seed
Write-Host "Seeding demo workspace and user..." -ForegroundColor Cyan
& "$PSScriptRoot\seed-demo.ps1"
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host ""
Write-Host "Done. Postgres and MinIO are running. Demo user: demo@trust.local / j" -ForegroundColor Green
Write-Host "Start the app with: npm run dev:full" -ForegroundColor White
