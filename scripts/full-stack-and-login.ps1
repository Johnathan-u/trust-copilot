# Full-stack bring-up and login verification.
# Prereq: Docker Desktop running. Frontend can be running separately on 3000 or will need to be started.
# Usage: from repo root, .\scripts\full-stack-and-login.ps1

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path $PSScriptRoot -Parent
if (-not (Test-Path (Join-Path $repoRoot "docker-compose.yml"))) { $repoRoot = (Get-Location).Path }
Set-Location $repoRoot

Write-Host "1. Checking Docker..."
$dockerOk = $false
try {
    docker ps 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { $dockerOk = $true }
} catch {}
if (-not $dockerOk) {
    Write-Host "Docker is not running. Start Docker Desktop, then run this script again."
    exit 1
}

Write-Host "2. Starting Postgres..."
docker compose up -d postgres
Start-Sleep -Seconds 5
$pg = docker compose ps postgres 2>&1
if ($pg -notmatch "Up") {
    Write-Host "Postgres may not be ready. Check: docker compose ps"
}

Write-Host "3. Starting API (background)..."
$apiJob = Start-Job -ScriptBlock {
    Set-Location $using:repoRoot
    node scripts/run-api.js
}
Start-Sleep -Seconds 8

Write-Host "4. Checking /healthz..."
$health = $null
try {
    $health = Invoke-WebRequest -Uri "http://localhost:8000/healthz" -UseBasicParsing -TimeoutSec 5
} catch {
    Write-Host "healthz failed: $_"
    Stop-Job $apiJob; Remove-Job $apiJob
    exit 1
}
Write-Host "healthz: $($health.StatusCode) $($health.Content)"

Write-Host "5. Running browser login verification (Playwright)..."
Push-Location (Join-Path $repoRoot "apps\web")
$env:BASE_URL = "http://localhost:3000"
node scripts/verify-browser.js
Pop-Location

Write-Host "6. Done. API is still running in background job. To stop: Stop-Job -Name $($apiJob.Name); Remove-Job $($apiJob.Name)"
Write-Host "Results: apps\web\verify-browser-results.md and .json"
