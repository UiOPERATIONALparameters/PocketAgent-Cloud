#!/usr/bin/env bash
# PocketAgent Cloud Daemon setup — runs on codespace creation.
# Installs common dev tools and starts the daemon in the background.

set -e

echo "=== PocketAgent Cloud Setup ==="

# Install common dev tools
echo "Installing dev tools..."
sudo apt-get update -qq
sudo apt-get install -y -qq ripgrep fd-find jq tree htop curl wget git > /dev/null 2>&1 || true

# Link fd as fdfind (some tools expect `fd`)
if command -v fdfind >/dev/null 2>&1 && ! command -v fd >/dev/null 2>&1; then
    sudo ln -sf "$(which fdfind)" /usr/local/bin/fd
fi

# Copy daemon to home
mkdir -p ~/.pocketagent
cp daemon.py ~/.pocketagent/daemon.py

# Generate auth token (optional, for extra security)
if [ ! -f ~/.pocketagent/token ]; then
    python3 -c "import secrets; print(secrets.token_urlsafe(32))" > ~/.pocketagent/token
    chmod 600 ~/.pocketagent/token
fi

echo "✓ Setup complete"
echo ""
echo "Starting PocketAgent daemon..."
cd ~/.pocketagent

# Start daemon in background, log to file
export POCKETAGENT_TOKEN=$(cat ~/.pocketagent/token)
nohup python3 daemon.py > ~/.pocketagent/daemon.log 2>&1 &
echo $! > ~/.pocketagent/daemon.pid
disown

sleep 2
if kill -0 $(cat ~/.pocketagent/daemon.pid) 2>/dev/null; then
    echo "✓ Daemon running (PID $(cat ~/.pocketagent/daemon.pid))"
    echo ""
    echo "=== Connection Info ==="
    echo "Public URL: https://${CODESPACE_NAME}-8765.app.github.dev"
    echo "Auth token: $(cat ~/.pocketagent/token)"
    echo ""
    echo "In the PocketAgent app:"
    echo "  1. Settings → Cloud → paste the URL above"
    echo "  2. Settings → Cloud → paste the token"
    echo "  3. Tap Connect"
else
    echo "✗ Daemon failed to start. Check ~/.pocketagent/daemon.log"
    cat ~/.pocketagent/daemon.log 2>/dev/null || true
fi
