#!/bin/bash
# =============================================================
# Trust Copilot — Server Setup & Deploy Script
# Run on a fresh Ubuntu 24.04 DigitalOcean Droplet
# Usage: bash deploy.sh
# =============================================================
set -euo pipefail

echo "=== Trust Copilot Production Deploy ==="

# 1. System updates
echo "[1/6] Updating system..."
apt-get update -qq && apt-get upgrade -y -qq

# 2. Install Docker
if ! command -v docker &> /dev/null; then
    echo "[2/6] Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
else
    echo "[2/6] Docker already installed"
fi

# 3. Install Docker Compose plugin (if not bundled)
if ! docker compose version &> /dev/null; then
    echo "[3/6] Installing Docker Compose plugin..."
    apt-get install -y -qq docker-compose-plugin
else
    echo "[3/6] Docker Compose already installed"
fi

# 4. Firewall
echo "[4/6] Configuring firewall..."
ufw allow 22/tcp   # SSH
ufw allow 80/tcp   # HTTP (Caddy redirect)
ufw allow 443/tcp  # HTTPS
ufw allow 443/udp  # HTTP/3 (QUIC)
ufw --force enable

# 5. Clone or pull repo
APP_DIR="/opt/trustcopilot"
if [ -d "$APP_DIR" ]; then
    echo "[5/6] Updating existing deploy..."
    cd "$APP_DIR"
    # Pull latest if git repo, otherwise just use what's there
    git pull 2>/dev/null || true
else
    echo "[5/6] Setting up app directory..."
    mkdir -p "$APP_DIR"
    echo "    Copy your project files to $APP_DIR"
    echo "    Then re-run this script."
    exit 0
fi

# 6. Build and start
echo "[6/6] Building and starting containers..."
cd "$APP_DIR"
docker compose -f docker-compose.prod.yml up -d --build

echo ""
echo "=== Deploy complete ==="
echo "Containers:"
docker ps --format "table {{.Names}}\t{{.Status}}"
echo ""
echo "Site should be live at: https://trustcopilot.app"
echo "(DNS must be pointing to this server's IP)"
