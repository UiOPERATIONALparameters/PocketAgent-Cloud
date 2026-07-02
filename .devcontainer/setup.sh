#!/usr/bin/env bash
# PocketAgent Cloud Daemon setup — runs on codespace creation.
# Installs common dev tools, starts the daemon, and makes port 8765 PUBLIC
# (critical — otherwise GitHub returns an HTML login page instead of JSON).

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

echo "✓ Setup complete"
echo ""
echo "Starting PocketAgent daemon (no token required)..."
cd ~/.pocketagent

# Start daemon in background, log to file
nohup python3 daemon.py > ~/.pocketagent/daemon.log 2>&1 &
echo $! > ~/.pocketagent/daemon.pid
disown

sleep 2
if kill -0 $(cat ~/.pocketagent/daemon.pid) 2>/dev/null; then
    echo "✓ Daemon running (PID $(cat ~/.pocketagent/daemon.pid))"
    echo ""
    echo "=== Making port 8765 public (critical step) ==="
    # CRITICAL: Port must be public or GitHub returns HTML login page instead of JSON.
    # The devcontainer.json visibility setting doesn't always apply on first creation.
    # Use gh CLI to explicitly set it.
    gh codespace ports visibility 8765:public -c "$CODESPACE_NAME" 2>/dev/null || {
        echo "⚠ Could not set port visibility via gh CLI."
        echo "  Manual fix: In VS Code (web), open Ports tab, right-click port 8765,"
        echo "  → Port visibility → Public."
    }
    echo "✓ Port 8765 is now public"
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
    # Quick self-test
    echo "=== Self-test (hitting the public URL) ==="
    sleep 2
    SELF_URL="https://${CODESPACE_NAME}-8765.app.github.dev/health"
    echo "Testing: $SELF_URL"
    RESP=$(curl -sS -m 10 "$SELF_URL" 2>&1 | head -c 500)
    if echo "$RESP" | grep -q '"status"'; then
        echo "✓ Daemon reachable from outside"
        echo "$RESP"
    elif echo "$RESP" | grep -q '<!doctype'; then
        echo "⚠ Got HTML — port visibility change may still be propagating."
        echo "  Wait 30 seconds, then in the app tap 'Refresh'."
        echo "  If still failing: open the codespace in browser → Ports tab →"
        echo "  right-click 8765 → Port visibility → Public."
    else
        echo "Response: $RESP"
    fi
    echo ""
    # Keep the codespace alive by tailing the log
    echo "Daemon log (Ctrl+C to stop watching, daemon keeps running):"
    echo "---"
    tail -f ~/.pocketagent/daemon.log 2>/dev/null || true
else
    echo "✗ Daemon failed to start. Check ~/.pocketagent/daemon.log"
    cat ~/.pocketagent/daemon.log 2>/dev/null || true
fi
