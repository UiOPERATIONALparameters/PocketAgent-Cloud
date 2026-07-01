# PocketAgent Cloud

This repo contains the devcontainer config for the PocketAgent cloud Linux environment.

When you create a GitHub Codespace from this repo, it automatically:
1. Installs Python 3.11, git, GitHub CLI, ripgrep, fd, jq, tree
2. Copies the PocketAgent daemon to `~/.pocketagent/`
3. Generates an auth token
4. Starts the daemon on port 8765 (exposed publicly via Codespaces port forwarding)

## Setup

1. Fork this repo (or use it directly as a template)
2. Create a codespace: `gh codespace create -r <your-fork>` or via GitHub.com → Code → Create codespace
3. Wait ~30 seconds for setup to complete
4. The codespace terminal prints the public URL + auth token
5. Open PocketAgent app → Settings → Cloud → paste URL + token → Connect

## What you get

- Real Ubuntu Linux (glibc, not Bionic)
- 4-core CPU, 16GB RAM (free tier)
- Persistent storage (32GB)
- Real apt — install anything: `sudo apt install openjdk-17 gradle nodejs rustc golang`
- Survives phone off, app uninstall, OS updates
- 60 hours/month free on GitHub Codespaces

## Architecture

```
PocketAgent App (phone)
   │
   │ HTTPS to https://<codespace>-8765.app.github.dev
   │
   ▼
GitHub Codespaces (real Linux VM)
   │
   ├── daemon.py (Python HTTP server on port 8765)
   │   - POST /exec — run command
   │   - GET /stream — live output
   │   - POST /files/* — file operations
   │   - POST /proc/* — process management
   │
   └── Real Ubuntu — bash, python, node, gcc, git, gradle, anything
```

## Files

- `.devcontainer/devcontainer.json` — Codespace config
- `.devcontainer/setup.sh` — Runs on creation
- `daemon.py` — The HTTP daemon
