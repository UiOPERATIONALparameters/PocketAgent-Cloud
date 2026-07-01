#!/usr/bin/env python3
"""
PocketAgent Cloud Daemon
=========================

Runs inside a GitHub Codespace. The PocketAgent Android app talks to it
over HTTPS (Codespaces handles TLS termination) to execute shell commands,
read/write files, and manage processes — in a REAL Linux environment.

This is the z.ai agentic mode pattern: real Linux, real glibc, real apt,
real everything. No Android fighting, no path patching, no seccomp.

The codespace's public URL (https://<name>-8765.app.github.dev) is unguessable,
so it serves as the auth. An optional token can be set via env var for extra security.

Endpoints (same as v6 Termux daemon):
  GET  /health, POST /exec, GET /stream, POST /proc/*, POST /files/*

Usage: python3 daemon.py  (started automatically by devcontainer.json)
"""

import http.server
import json
import os
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path

HOST = "0.0.0.0"  # Bind to all interfaces so Codespaces can forward
PORT = 8765
VERSION = "7.0.0"
HOME = Path(os.path.expanduser("~"))
TOKEN = os.environ.get("POCKETAGENT_TOKEN", "")  # Optional; if set, required
MAX_FILE_READ = 2_000_000  # 2MB for cloud (more generous than phone)
MAX_OUTPUT = 2_000_000

_processes = {}
_processes_lock = threading.Lock()
START_TIME = time.time()


def check_token(headers):
    if not TOKEN:
        return True
    return headers.get("X-PocketAgent-Token", "") == TOKEN


def resolve_path(path_str):
    if not path_str:
        return None
    p = Path(path_str).expanduser()
    if not p.is_absolute():
        p = HOME / p
    try:
        p = p.resolve()
    except Exception:
        return None
    # In cloud mode, allow anywhere under HOME (more permissive than v6)
    try:
        p.relative_to(HOME)
    except ValueError:
        # Allow /tmp and /workspace too
        if not (str(p).startswith("/tmp") or str(p).startswith("/workspace")):
            return None
    return p


def execute_command(command, timeout=120, cwd=None):
    start = time.time()
    cwd_path = resolve_path(cwd) if cwd else HOME
    if cwd_path is None:
        cwd_path = HOME
    try:
        proc = subprocess.Popen(
            ["bash", "-l", "-c", command],
            cwd=str(cwd_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except Exception as e:
        return {"stdout": "", "stderr": f"Failed to start: {e}", "exit_code": -1,
                "duration_ms": int((time.time() - start) * 1000), "pid": None, "error": str(e)}

    with _processes_lock:
        _processes[proc.pid] = {"command": command, "started_at": start, "proc": proc}
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        exit_code = proc.returncode
        timed_out = False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except Exception:
            proc.kill()
        try:
            stdout, stderr = proc.communicate(timeout=2)
        except Exception:
            stdout, stderr = b"", b"timed out"
        exit_code = -1
        timed_out = True

    with _processes_lock:
        _processes.pop(proc.pid, None)

    return {
        "stdout": stdout.decode("utf-8", errors="replace")[:MAX_OUTPUT],
        "stderr": stderr.decode("utf-8", errors="replace")[:MAX_OUTPUT],
        "exit_code": exit_code,
        "duration_ms": int((time.time() - start) * 1000),
        "pid": proc.pid,
        "timed_out": timed_out,
        "truncated": len(stdout) > MAX_OUTPUT or len(stderr) > MAX_OUTPUT,
        "suggestion": _suggest(stderr.decode("utf-8", errors="replace"), stdout.decode("utf-8", errors="replace")) if exit_code != 0 and not timed_out else None,
    }


def _suggest(stderr, stdout):
    s = (stderr + " " + stdout).lower()
    if "command not found" in s:
        return "Install it: `sudo apt install <name>` or `pip install <name>`."
    if "unable to locate package" in s:
        return "Run `sudo apt update` first."
    if "permission denied" in s:
        return "Try `chmod +x <file>` or use `sudo`."
    if "no such file or directory" in s:
        return "Check the path with `ls`."
    if "no module named" in s:
        return "Install it: `pip install <module>`."
    if "could not resolve host" in s:
        return "DNS failed — check internet connection."
    return None


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = f"PocketAgentCloud/{VERSION}"

    def log_message(self, *args):
        pass  # quiet

    def _send_json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception as e:
            return {"_parse_error": str(e)}

    def _authed(self):
        if not check_token(self.headers):
            self._send_json(401, {"error": "unauthorized"})
            return False
        return True

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-PocketAgent-Token")
        self.end_headers()

    def do_GET(self):
        if not self._authed():
            return
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/health":
            self._send_json(200, {
                "status": "ok", "version": VERSION,
                "user": os.environ.get("USER", "unknown"),
                "home": str(HOME), "uptime": int(time.time() - START_TIME),
                "processes": len(_processes), "mode": "cloud"
            })
            return
        if parsed.path == "/stream":
            self._handle_stream(parsed.query)
            return
        self._send_json(404, {"error": f"unknown: {parsed.path}"})

    def do_POST(self):
        if not self._authed():
            return
        parsed = urllib.parse.urlparse(self.path)
        body = self._read_body()
        if "_parse_error" in body:
            self._send_json(400, {"error": "invalid JSON"})
            return
        if parsed.path == "/exec":
            cmd = body.get("command")
            if not cmd:
                self._send_json(400, {"error": "missing 'command'"})
                return
            timeout = max(1, min(int(body.get("timeout", 120)), 1800))
            self._send_json(200, execute_command(cmd, timeout, body.get("cwd")))
        elif parsed.path == "/proc/list":
            with _processes_lock:
                procs = [{"pid": p, "command": i["command"], "started_at": i["started_at"],
                          "duration_s": int(time.time() - i["started_at"])} for p, i in _processes.items()]
            self._send_json(200, {"processes": procs})
        elif parsed.path == "/proc/kill":
            pid = body.get("pid")
            if not pid:
                self._send_json(400, {"error": "missing 'pid'"})
                return
            try:
                os.killpg(int(pid), signal.SIGTERM)
                self._send_json(200, {"killed": True, "pid": pid})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
        elif parsed.path == "/files/read":
            p = resolve_path(body.get("path"))
            if not p or not p.exists():
                self._send_json(404, {"error": "not found"})
                return
            size = p.stat().st_size
            content = p.read_bytes()[:MAX_FILE_READ]
            try:
                text = content.decode("utf-8")
                binary = False
            except UnicodeDecodeError:
                text = "(binary file)"
                binary = True
            self._send_json(200, {"content": text, "size": size, "truncated": size > MAX_FILE_READ,
                                  "binary": binary, "path": str(p)})
        elif parsed.path == "/files/write":
            p = resolve_path(body.get("path"))
            if not p:
                self._send_json(400, {"error": "invalid path"})
                return
            p.parent.mkdir(parents=True, exist_ok=True)
            data = body.get("content", "").encode("utf-8")
            p.write_bytes(data)
            self._send_json(200, {"bytes": len(data), "path": str(p)})
        elif parsed.path == "/files/list":
            p = resolve_path(body.get("path", "~"))
            if not p or not p.exists():
                self._send_json(404, {"error": "not found"})
                return
            entries = []
            if p.is_dir():
                for e in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                    try:
                        st = e.stat()
                        entries.append({"name": e.name, "type": "dir" if e.is_dir() else "file",
                                        "size": st.st_size if e.is_file() else 0, "mtime": int(st.st_mtime),
                                        "hidden": e.name.startswith(".")})
                    except Exception:
                        continue
            self._send_json(200, {"entries": entries, "path": str(p)})
        elif parsed.path == "/files/stat":
            p = resolve_path(body.get("path"))
            if not p or not p.exists():
                self._send_json(200, {"exists": False})
                return
            st = p.stat()
            self._send_json(200, {"exists": True, "type": "dir" if p.is_dir() else "file",
                                  "size": st.st_size if p.is_file() else 0, "mtime": int(st.st_mtime), "path": str(p)})
        elif parsed.path == "/files/mkdir":
            p = resolve_path(body.get("path"))
            if p:
                p.mkdir(parents=True, exist_ok=True)
                self._send_json(200, {"created": True, "path": str(p)})
            else:
                self._send_json(400, {"error": "invalid path"})
        elif parsed.path == "/files/delete":
            p = resolve_path(body.get("path"))
            if p and p.exists():
                if p.is_dir():
                    import shutil
                    shutil.rmtree(p)
                else:
                    p.unlink()
                self._send_json(200, {"deleted": True})
            else:
                self._send_json(404, {"error": "not found"})
        else:
            self._send_json(404, {"error": f"unknown: {parsed.path}"})

    def _handle_stream(self, query):
        params = urllib.parse.parse_qs(query)
        cmd = params.get("command", [""])[0]
        if not cmd:
            self._send_json(400, {"error": "missing 'command'"})
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        cwd_path = HOME
        try:
            proc = subprocess.Popen(["bash", "-l", "-c", cmd], cwd=str(cwd_path),
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1,
                                    universal_newlines=True, start_new_session=True)
            with _processes_lock:
                _processes[proc.pid] = {"command": cmd, "started_at": time.time(), "proc": proc}
            for line in iter(proc.stdout.readline, ""):
                try:
                    self.wfile.write((json.dumps({"type": "output", "data": line}) + "\n").encode())
                    self.wfile.flush()
                except Exception:
                    break
            proc.wait()
            try:
                self.wfile.write((json.dumps({"type": "exit", "code": proc.returncode}) + "\n").encode())
            except Exception:
                pass
            with _processes_lock:
                _processes.pop(proc.pid, None)
        except Exception as e:
            try:
                self.wfile.write((json.dumps({"type": "error", "message": str(e)}) + "\n").encode())
            except Exception:
                pass


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    print(f"""
╔══════════════════════════════════════════════════╗
║  PocketAgent Cloud Daemon v{VERSION}                ║
║  Listening on http://{HOST}:{PORT}                    ║
║  Home: {str(HOME):<38} ║
║  Mode: CLOUD (GitHub Codespaces)                 ║
╚══════════════════════════════════════════════════╝

Codespace public URL: https://$CODESPACE_NAME-8765.app.github.dev
(The PocketAgent app connects to this URL.)

Press Ctrl+C to stop.
""", flush=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping...", flush=True)
        server.shutdown()
        sys.exit(0)


if __name__ == "__main__":
    main()
