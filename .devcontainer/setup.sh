#!/usr/bin/env bash
# PocketAgent Cloud Daemon setup — runs on codespace creation.
# Installs common dev tools and starts the daemon in the background.
# Token is OPTIONAL — the codespace URL is already unguessable.

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

# NOTE: Token is OPTIONAL. The codespace URL is already unguessable.
# If you want extra auth, create ~/.pocketagent/token manually and the
# daemon will read it via POCKETAGENT_TOKEN env var. By default, no token.

echo "✓ Setup complete"
echo ""
echo "Starting PocketAgent daemon (no token required)..."
cd ~/.pocketagent

# Start daemon in background, log to file
# POCKETAGENT_TOKEN is empty by default — no auth needed
nohup python3 daemon.py > ~/.pocketagent/daemon.log 2>&1 &
echo $! > ~/.pocketagent/daemon.pid
disown

sleep 2
if kill -0 $(cat ~/.pocketagent/daemon.pid) 2>/dev/null; then
    echo "✓ Daemon running (PID $(cat ~/.pocketagent/daemon.pid))"
    echo ""
    echo "=== Connection Info ==="
    echo ""
    echo "In the PocketAgent app → Settings → Cloud Linux:"
    echo ""
    echo "  Codespace URL: https://${CODESPACE_NAME}-8765.app.github.dev"
    echo "  Daemon Token: (leave empty)"
    echo ""
    echo "Tap 'Save & Connect'. You're done!"
    echo ""
    # Keep the codespace alive by tailing the log
    echo "Daemon log (Ctrl+C to stop watching, daemon keeps running):"
    echo "---"
    tail -f ~/.pocketagent/daemon.log 2>/dev/null || true
else
    echo "✗ Daemon failed to start. Check ~/.pocketagent/daemon.log"
    cat ~/.pocketagent/daemon.log 2>/dev/null || true
fi
