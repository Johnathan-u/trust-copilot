# Start Trust Copilot for local use.
# Usage: .\scripts\start.ps1
# Then open http://localhost and login with demo@trust.local / j

$Root = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $Root ".env"

# Create .env from example if missing
if (-not (Test-Path $EnvFile)) {
  Copy-Item (Join-Path $Root ".env.example") $EnvFile
  Write-Host "Created .env from .env.example. Add your OPENAI_API_KEY to .env for AI generation."
}

Set-Location $Root

# Start services
Write-Host "Starting services..."
docker compose up -d

# Wait for postgres
Start-Sleep -Seconds 5

# Run migrations
Write-Host "Running migrations..."
docker compose exec -T api alembic upgrade head

# Seed demo (creates sample data)
Write-Host "Seeding demo workspace..."
docker compose exec -T api python scripts/seed_demo_workspace.py 2>$null

Set-Location $Root
Write-Host ""
Write-Host "Trust Copilot is running (web, api, worker, postgres, minio, caddy)."
Write-Host "  App:    http://localhost"
Write-Host "  Login:  demo@trust.local / j"
Write-Host ""
Write-Host "Add OPENAI_API_KEY to .env for AI answer generation."
