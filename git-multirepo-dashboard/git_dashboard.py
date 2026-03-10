#!/usr/bin/env python3
"""Git Fleet — multi-repo git dashboard.

Usage:
    python git_dashboard.py [--port N] [--no-browser] [--scan PATH] [--yes|-y]
"""

# ── stdlib-only imports (safe before bootstrap) ───────────────────────────────
import os
import sys
import shutil
import socket
import signal
import argparse
import sqlite3
import subprocess
import webbrowser
from pathlib import Path
from threading import Timer

# ── Bootstrap constants ───────────────────────────────────────────────────────
VENV_DIR = Path.home() / ".git_dashboard_venv"
DATA_DIR = Path.home() / ".git_dashboard"
DB_PATH = DATA_DIR / "dashboard.db"
DEFAULT_PORT = 8300
DEPENDENCIES = ["fastapi", "uvicorn[standard]", "aiosqlite", "packaging"]
VERSION = "0.1.0"

# Populated by build_tools_dict() during preflight; global so /api/status can
# return it without re-running which() on every request.
TOOLS: dict = {}


# ── Bootstrap ─────────────────────────────────────────────────────────────────

def bootstrap() -> None:
    """Ensure the app runs inside a proper venv with all dependencies.

    1. If all required packages are importable, return immediately.
    2. Otherwise, create the venv (if needed), install deps, then re-exec.
    """
    try:
        import fastapi   # noqa: F401
        import uvicorn   # noqa: F401
        import aiosqlite # noqa: F401
        import packaging # noqa: F401
        return
    except ImportError:
        pass

    venv_python = (
        VENV_DIR / "Scripts" / "python.exe"
        if sys.platform == "win32"
        else VENV_DIR / "bin" / "python"
    )

    if not venv_python.exists():
        print("Git Fleet: creating virtual environment…", flush=True)
        subprocess.run(
            [sys.executable, "-m", "venv", str(VENV_DIR)],
            check=True,
        )

    print("Git Fleet: installing dependencies…", flush=True)
    subprocess.run(
        [str(venv_python), "-m", "pip", "install", "--quiet"] + DEPENDENCIES,
        check=True,
    )

    if sys.platform == "win32":
        result = subprocess.run([str(venv_python)] + sys.argv)
        sys.exit(result.returncode)
    else:
        os.execv(str(venv_python), [str(venv_python)] + sys.argv)


bootstrap()

# ── Third-party imports (safe after bootstrap) ────────────────────────────────
from fastapi import FastAPI          # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402
import uvicorn                       # noqa: E402


# ── Preflight checks ──────────────────────────────────────────────────────────

def check_python_version() -> None:
    """Hard-fail if Python < 3.9."""
    if sys.version_info < (3, 9):
        print(
            f"Error: Python 3.9+ required. Found {sys.version}. "
            "Install from python.org.",
            file=sys.stderr,
        )
        sys.exit(1)


def check_git() -> None:
    """Hard-fail if git is not in PATH."""
    if shutil.which("git") is None:
        print(
            "Error: git not found in PATH. Install from https://git-scm.com/",
            file=sys.stderr,
        )
        sys.exit(1)


def build_tools_dict() -> dict:
    """Return a dict mapping tool names to their PATH location (or None)."""
    tools: dict = {}

    # Primary ecosystem tools — always checked
    for name, cmd in [
        ("npm", "npm"),
        ("go", "go"),
        ("cargo", "cargo"),
        ("bundle", "bundle"),
        ("composer", "composer"),
    ]:
        tools[name] = shutil.which(cmd)

    # Conditional tools — only checked when the parent tool is present
    tools["govulncheck"] = shutil.which("govulncheck") if tools["go"] else None
    tools["cargo_audit"] = shutil.which("cargo-audit") if tools["cargo"] else None
    tools["cargo_outdated"] = shutil.which("cargo-outdated") if tools["cargo"] else None
    tools["bundler_audit"] = shutil.which("bundler-audit") if tools["bundle"] else None

    # pip_audit: may live inside the venv; check unconditionally
    tools["pip_audit"] = shutil.which("pip-audit")

    return tools


def check_ecosystem_tools(tools: dict) -> None:
    """Hard-fail if no ecosystem dependency tools are found at all.

    Ecosystem tools: npm, go, cargo, bundle, composer, pip_audit.
    --yes does NOT override this check.
    """
    ecosystem_keys = ["npm", "go", "cargo", "bundle", "composer", "pip_audit"]
    if not any(tools.get(k) for k in ecosystem_keys):
        print(
            "\nError: No dependency tools found. The dashboard requires at least one "
            "ecosystem tool to be useful. Install one or more of the tools listed "
            "above and try again.",
            file=sys.stderr,
        )
        sys.exit(1)


def _tool_display_name(key: str) -> str:
    mapping = {
        "npm": "npm",
        "go": "go",
        "cargo": "cargo",
        "bundle": "bundle",
        "composer": "composer",
        "govulncheck": "govulncheck",
        "cargo_audit": "cargo-audit",
        "cargo_outdated": "cargo-outdated",
        "bundler_audit": "bundler-audit",
        "pip_audit": "pip-audit",
    }
    return mapping.get(key, key)


def _print_preflight_summary(tools: dict) -> None:
    """Print the preflight summary table to stderr."""
    print("Git Fleet - Preflight Check", file=sys.stderr)
    print("============================", file=sys.stderr)
    print(file=sys.stderr)

    def _status_line(display: str, path) -> str:
        dots = "." * max(1, 18 - len(display))
        if path:
            return f"  {display} {dots} OK"
        return f"  {display} {dots} NOT FOUND"

    # git — always shown first
    git_path = shutil.which("git")
    print(_status_line("git", git_path), file=sys.stderr)
    print(file=sys.stderr)

    # Primary optional tools and their sub-tools
    primary_order = [
        ("npm", [], ["  -> Node.js dependency checks will be disabled."]),
        ("go", ["govulncheck"], [
            "  -> Go dependency checks will be disabled.",
        ]),
        ("cargo", ["cargo_audit", "cargo_outdated"], [
            "  -> All Rust dependency checks will be disabled.",
        ]),
        ("bundle", ["bundler_audit"], [
            "  -> All Ruby dependency checks will be disabled.",
        ]),
        ("composer", [], [
            "  -> PHP dependency checks will be disabled.",
        ]),
        ("pip_audit", [], [
            "  -> Python vulnerability scanning will be disabled.",
            "  -> Outdated checks still work via PyPI API.",
            "  -> Install with: pip install pip-audit",
        ]),
    ]

    for primary, children, missing_msgs in primary_order:
        path = tools.get(primary)
        name = _tool_display_name(primary)
        print(_status_line(name, path), file=sys.stderr)
        if not path:
            for msg in missing_msgs:
                print(msg, file=sys.stderr)
        else:
            # Show sub-tools if parent found
            for child in children:
                child_path = tools.get(child)
                child_name = _tool_display_name(child)
                print(_status_line(child_name, child_path), file=sys.stderr)
                if not child_path:
                    # Minimal hint for missing sub-tools
                    pass
        print(file=sys.stderr)


def run_preflight(yes: bool = False) -> None:
    """Run all preflight checks. Mutates the module-level TOOLS dict."""
    global TOOLS

    check_python_version()
    check_git()

    TOOLS = build_tools_dict()

    # Hard-fail if no ecosystem tools at all (--yes does not override)
    check_ecosystem_tools(TOOLS)

    # Determine if any optional tools are missing
    ecosystem_keys = ["npm", "go", "cargo", "bundle", "composer", "pip_audit"]
    missing_any = not all(TOOLS.get(k) for k in ecosystem_keys)

    _print_preflight_summary(TOOLS)

    if not missing_any:
        # All optional tools present — no prompt needed
        return

    print(
        "Some dependency tools are missing. Results may be incomplete.",
        file=sys.stderr,
    )

    if yes:
        return

    try:
        answer = input("Continue anyway? [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = ""

    if answer == "n":
        print("Exiting. Install the missing tools and try again.")
        sys.exit(0)


# ── SQLite Schema ─────────────────────────────────────────────────────────────

_SCHEMA_SQL = """\
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS repositories (
  id                  TEXT PRIMARY KEY,
  name                TEXT NOT NULL,
  path                TEXT NOT NULL UNIQUE,
  default_branch      TEXT DEFAULT 'main',
  runtime             TEXT,
  added_at            TEXT NOT NULL,
  last_quick_scan_at  TEXT,
  last_full_scan_at   TEXT
);

CREATE TABLE IF NOT EXISTS daily_stats (
  repo_id        TEXT    NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  date           TEXT    NOT NULL,
  commits        INTEGER DEFAULT 0,
  insertions     INTEGER DEFAULT 0,
  deletions      INTEGER DEFAULT 0,
  files_changed  INTEGER DEFAULT 0,
  PRIMARY KEY (repo_id, date)
);

CREATE TABLE IF NOT EXISTS branches (
  repo_id           TEXT    NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  name              TEXT    NOT NULL,
  last_commit_date  TEXT,
  is_default        BOOLEAN DEFAULT FALSE,
  is_stale          BOOLEAN DEFAULT FALSE,
  PRIMARY KEY (repo_id, name)
);

CREATE TABLE IF NOT EXISTS dependencies (
  repo_id          TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  manager          TEXT NOT NULL,
  name             TEXT NOT NULL,
  current_version  TEXT,
  wanted_version   TEXT,
  latest_version   TEXT,
  severity         TEXT DEFAULT 'ok',
  advisory_id      TEXT,
  checked_at       TEXT,
  PRIMARY KEY (repo_id, manager, name)
);

CREATE TABLE IF NOT EXISTS working_state (
  repo_id              TEXT PRIMARY KEY REFERENCES repositories(id) ON DELETE CASCADE,
  has_uncommitted      BOOLEAN DEFAULT FALSE,
  modified_count       INTEGER DEFAULT 0,
  untracked_count      INTEGER DEFAULT 0,
  staged_count         INTEGER DEFAULT 0,
  current_branch       TEXT,
  last_commit_hash     TEXT,
  last_commit_message  TEXT,
  last_commit_date     TEXT,
  checked_at           TEXT
);

CREATE TABLE IF NOT EXISTS scan_log (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  scan_type       TEXT NOT NULL,
  started_at      TEXT NOT NULL,
  finished_at     TEXT,
  repos_scanned   INTEGER DEFAULT 0,
  status          TEXT DEFAULT 'running'
);
"""


def init_schema(db_path: Path) -> None:
    """Create all tables (idempotent) and enable WAL mode.

    Uses synchronous sqlite3 — called once at startup before uvicorn starts.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


# ── Port selection ────────────────────────────────────────────────────────────

def find_free_port(start_port: int, max_attempts: int = 20) -> int:
    """Return the first free TCP port at or after start_port."""
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(
        f"No free port found in range {start_port}–{start_port + max_attempts - 1}"
    )


# ── CLI args ──────────────────────────────────────────────────────────────────

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="git_dashboard",
        description="Git Fleet — multi-repo git dashboard",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        metavar="N",
        help=f"Port to listen on (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Skip opening a browser tab on startup",
    )
    parser.add_argument(
        "--scan",
        metavar="PATH",
        help="Register and scan a directory on startup (wired in packet 02/03)",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip missing-tools confirmation prompt (for scripted launches)",
    )
    return parser.parse_args(argv)


# ── HTML placeholder template ─────────────────────────────────────────────────
# Full SPA is delivered in packets 04–05.  This minimal page confirms the
# server is up and includes the CDN tags specified in spec section 5.1.

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Git Fleet</title>
  <!-- CDN dependencies (pinned versions per spec §5.1) -->
  <script crossorigin src="https://cdnjs.cloudflare.com/ajax/libs/react/18.2.0/umd/react.production.min.js"></script>
  <script crossorigin src="https://cdnjs.cloudflare.com/ajax/libs/react-dom/18.2.0/umd/react-dom.production.min.js"></script>
  <script crossorigin src="https://cdnjs.cloudflare.com/ajax/libs/babel-standalone/7.23.9/babel.min.js"></script>
  <script crossorigin src="https://cdnjs.cloudflare.com/ajax/libs/recharts/2.12.7/Recharts.min.js"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Geist:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Geist', -apple-system, 'Segoe UI', system-ui, sans-serif;
      background: #0d1117;
      color: #e6edf3;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
    }
    .placeholder {
      text-align: center;
      padding: 2rem;
    }
    h1 {
      font-family: 'JetBrains Mono', 'Courier New', monospace;
      font-size: 1.5rem;
      margin-bottom: 0.5rem;
    }
    p { color: #8b949e; font-size: 0.9rem; }
  </style>
</head>
<body>
  <div class="placeholder">
    <h1>Git Fleet</h1>
    <p>Server is running. Full UI coming in packets 04–05.</p>
  </div>
</body>
</html>
"""


# ── FastAPI application ───────────────────────────────────────────────────────

app = FastAPI(title="Git Fleet")


@app.get("/", response_class=HTMLResponse)
async def get_ui():
    """Serve the SPA shell (placeholder until packet 04)."""
    return HTML_TEMPLATE


@app.get("/api/status")
async def get_status():
    """Return tool availability and app version for the frontend banner."""
    return {"tools": TOOLS, "version": VERSION}


# ── Signal handling ───────────────────────────────────────────────────────────

def _shutdown_handler(sig, frame):
    print("\nGit Fleet: shutting down.", flush=True)
    sys.exit(0)


def register_signal_handlers() -> None:
    signal.signal(signal.SIGINT, _shutdown_handler)
    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, _shutdown_handler)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()

    run_preflight(yes=args.yes)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    init_schema(DB_PATH)

    port = find_free_port(args.port)
    if port != args.port:
        print(
            f"Warning: Port {args.port} is in use; using port {port} instead.",
            flush=True,
        )

    url = f"http://localhost:{port}"
    print(f"Git Fleet running at {url}", flush=True)

    if not args.no_browser:
        Timer(1.0, webbrowser.open, args=[url]).start()

    register_signal_handlers()

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
