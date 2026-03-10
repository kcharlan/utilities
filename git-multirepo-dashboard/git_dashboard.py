#!/usr/bin/env python3
"""Git Fleet — multi-repo git dashboard.

Usage:
    python git_dashboard.py [--port N] [--no-browser] [--scan PATH] [--yes|-y]
"""

# ── stdlib-only imports (safe before bootstrap) ───────────────────────────────
import asyncio
import hashlib
import os
import sys
import shutil
import socket
import signal
import argparse
import sqlite3
import subprocess
import webbrowser
from datetime import datetime, timezone
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
import aiosqlite                     # noqa: E402
from fastapi import Depends, FastAPI, HTTPException  # noqa: E402
from fastapi.responses import HTMLResponse, Response  # noqa: E402
from pydantic import BaseModel       # noqa: E402
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


# ── Git Quick Scan ────────────────────────────────────────────────────────────

async def run_git(repo_path, *args: str) -> tuple:
    """Run a git command and return (stdout, stderr, returncode).

    Always uses asyncio.create_subprocess_exec (never shell=True).
    Decodes output with errors='replace' to handle non-UTF8 commit messages.
    """
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", str(repo_path), *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return (
        stdout.decode("utf-8", errors="replace").strip(),
        stderr.decode("utf-8", errors="replace").strip(),
        proc.returncode,
    )


async def is_valid_repo(repo_path) -> bool:
    """Return True if repo_path is inside a git work tree, False otherwise."""
    try:
        _, _, rc = await run_git(repo_path, "rev-parse", "--is-inside-work-tree")
        return rc == 0
    except Exception:
        return False


def parse_porcelain_status(output: str) -> dict:
    """Parse 'git status --porcelain=v1' output into working-tree counts.

    Each line is 'XY filename' where:
      X = index (staging area) status
      Y = worktree status
      '??' = untracked

    Rules:
      - X not in (' ', '?') → staged_count += 1
      - Y == 'M'             → modified_count += 1
      - XY == '??'           → untracked_count += 1
      - any non-empty output → has_uncommitted = True
    """
    modified_count = 0
    untracked_count = 0
    staged_count = 0
    has_uncommitted = False

    for line in output.splitlines():
        if len(line) < 2:
            continue
        has_uncommitted = True
        x = line[0]
        y = line[1]
        if x == "?" and y == "?":
            untracked_count += 1
        else:
            if x not in (" ", "?"):
                staged_count += 1
            if y == "M":
                modified_count += 1

    return {
        "modified_count": modified_count,
        "untracked_count": untracked_count,
        "staged_count": staged_count,
        "has_uncommitted": has_uncommitted,
    }


def parse_last_commit(output: str) -> dict:
    """Parse 'git log -1 --format=%H%x00%aI%x00%s' output.

    Returns a dict with hash, date, message — all None if output is empty
    (repo has zero commits).
    """
    if not output:
        return {"hash": None, "date": None, "message": None}
    parts = output.split("\x00", 2)
    return {
        "hash": parts[0] if len(parts) > 0 else None,
        "date": parts[1] if len(parts) > 1 else None,
        "message": parts[2] if len(parts) > 2 else None,
    }


async def get_current_branch(repo_path) -> str | None:
    """Return the current branch name, or None if repo has no commits."""
    stdout, _, rc = await run_git(repo_path, "rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0:
        return None
    # "HEAD" means detached or empty repo
    if stdout == "HEAD":
        return None
    return stdout or None


async def quick_scan_repo(repo_path) -> dict:
    """Run the 4-command quick scan for a single repo.

    Returns a dict with all fields needed for working_state:
      has_uncommitted, modified_count, untracked_count, staged_count,
      current_branch, last_commit_hash, last_commit_date, last_commit_message.

    Runs commands sequentially (they're fast; parallelism across repos is in packet 03).
    """
    repo_path = str(repo_path)

    # 1. Status
    status_out, _, _ = await run_git(repo_path, "status", "--porcelain=v1")
    status = parse_porcelain_status(status_out)

    # 2. Last commit
    log_out, _, log_rc = await run_git(
        repo_path, "log", "-1", "--format=%H%x00%aI%x00%s"
    )
    # rc 128 means empty repo (no commits); handle gracefully
    commit = parse_last_commit(log_out if log_rc == 0 else "")

    # 3. Current branch
    branch = await get_current_branch(repo_path)

    return {
        "has_uncommitted": status["has_uncommitted"],
        "modified_count": status["modified_count"],
        "untracked_count": status["untracked_count"],
        "staged_count": status["staged_count"],
        "current_branch": branch,
        "last_commit_hash": commit["hash"],
        "last_commit_date": commit["date"],
        "last_commit_message": commit["message"],
    }


async def upsert_working_state(db, repo_id: str, data: dict) -> None:
    """Write quick-scan results to working_state table (insert or replace)."""
    await db.execute(
        """
        INSERT OR REPLACE INTO working_state
          (repo_id, has_uncommitted, modified_count, untracked_count,
           staged_count, current_branch, last_commit_hash,
           last_commit_message, last_commit_date, checked_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            repo_id,
            data["has_uncommitted"],
            data["modified_count"],
            data["untracked_count"],
            data["staged_count"],
            data["current_branch"],
            data["last_commit_hash"],
            data["last_commit_message"],
            data["last_commit_date"],
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    await db.commit()


# ── Fleet Quick Scan ──────────────────────────────────────────────────────────

async def scan_fleet_quick(db) -> list:
    """Quick-scan all registered repos in parallel (semaphore=8), upsert working_state.

    Repos whose disk paths no longer exist are skipped (omitted from results).
    Returns a list of dicts containing repo metadata + quick-scan data.
    """
    cursor = await db.execute(
        "SELECT id, name, path, runtime, default_branch FROM repositories"
    )
    rows = await cursor.fetchall()
    if not rows:
        return []

    sem = asyncio.Semaphore(8)

    async def scan_one(repo_row):
        repo_id, name, path, runtime, default_branch = repo_row
        async with sem:
            if not Path(path).is_dir():
                return None  # skip missing repos
            data = await quick_scan_repo(path)
            await upsert_working_state(db, repo_id, data)
            return {
                "id": repo_id,
                "name": name,
                "path": path,
                "runtime": runtime,
                "default_branch": default_branch,
                **data,
            }

    results = await asyncio.gather(*(scan_one(r) for r in rows))
    return [r for r in results if r is not None]


# ── Repo Discovery & Registration ─────────────────────────────────────────────

def generate_repo_id(absolute_path: str) -> str:
    """Return a 16-char hex ID derived from sha256 of the absolute path."""
    return hashlib.sha256(absolute_path.encode()).hexdigest()[:16]


def detect_runtime(repo_path: Path) -> str:
    """Classify the primary language/runtime for a repo by detecting ecosystem files.

    Checks files in priority order per spec section 3.4. Returns "mixed" when
    multiple language ecosystems are detected (docker does not count toward mixed).
    """
    # Priority 1–9: language/ecosystem files
    ecosystem_checks = [
        (["pyproject.toml"], "python"),
        (["requirements.txt"], "python"),
        (["setup.py", "setup.cfg"], "python"),
        (["package.json"], "node"),
        (["go.mod"], "go"),
        (["Cargo.toml"], "rust"),
        (["Gemfile"], "ruby"),
        (["composer.json"], "php"),
        (["Dockerfile", "docker-compose.yml", "docker-compose.yaml"], "docker"),
    ]

    found: set = set()
    try:
        dir_files = {p.name.lower() for p in repo_path.iterdir() if p.is_file()}
    except (OSError, PermissionError):
        return "unknown"

    for files, runtime in ecosystem_checks:
        for f in files:
            if f.lower() in dir_files:
                found.add(runtime)
                break

    if len(found) == 0:
        # Priority 10: shell-heavy (majority of files have shell extensions)
        shell_exts = {".sh", ".zsh", ".bat", ".ps1"}
        try:
            all_files = [p for p in repo_path.iterdir() if p.is_file()]
            if all_files:
                shell_count = sum(1 for f in all_files if f.suffix.lower() in shell_exts)
                if shell_count / len(all_files) > 0.5:
                    return "shell"
        except (OSError, PermissionError):
            pass
        # Priority 11: index.html at root
        if "index.html" in dir_files:
            return "html"
        return "unknown"

    if len(found) == 1:
        return found.pop()

    # Multiple ecosystems detected — filter out docker (it's packaging, not a runtime)
    non_docker = found - {"docker"}
    if not non_docker:
        return "docker"
    if len(non_docker) == 1:
        return non_docker.pop()
    return "mixed"


async def get_default_branch(repo_path: Path) -> str:
    """Return the current branch name from symbolic-ref, or 'main' as fallback."""
    stdout, _, rc = await run_git(repo_path, "symbolic-ref", "--short", "HEAD")
    if rc == 0 and stdout:
        return stdout
    return "main"


# Directories to skip when walking for git repos
_DISCOVERY_SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".tox", ".eggs", "dist", "build",
}


async def discover_repos(root_path: Path) -> list:
    """Recursively walk root_path and return info dicts for all git repos found.

    Skips hidden directories (starting with '.') and known non-repo directories.
    Stops descending into a directory once a .git is found (avoids submodule traversal).
    Uses git rev-parse --show-toplevel for deduplication (belt-and-suspenders).

    Returns list of dicts with keys: path (str, resolved), name (str).
    """
    candidates: list = []

    # Synchronous walk — just checking directory existence, no git I/O
    for dirpath, dirnames, _ in os.walk(str(root_path)):
        # Prune hidden dirs and known skip dirs (in-place to affect os.walk descent)
        dirnames[:] = [
            d for d in dirnames
            if d not in _DISCOVERY_SKIP_DIRS and not d.startswith(".")
        ]

        git_dir = Path(dirpath) / ".git"
        if git_dir.exists():
            candidates.append(Path(dirpath))
            dirnames.clear()  # Don't descend further into this repo

    # Async deduplication via git rev-parse --show-toplevel
    repos: list = []
    seen_toplevel: set = set()
    for candidate in candidates:
        stdout, _, rc = await run_git(candidate, "rev-parse", "--show-toplevel")
        if rc != 0:
            continue
        try:
            toplevel = Path(stdout).resolve()
        except OSError:
            toplevel = Path(stdout)
        key = str(toplevel)
        if key not in seen_toplevel:
            seen_toplevel.add(key)
            repos.append({"path": key, "name": toplevel.name})

    return repos


async def register_repo(db, repo_info: dict) -> dict:
    """Insert a repo into the repositories table (idempotent via INSERT OR IGNORE).

    repo_info must have keys: path, name, default_branch, runtime.
    Returns dict with id, name, path.
    """
    repo_id = generate_repo_id(repo_info["path"])
    await db.execute(
        """INSERT OR IGNORE INTO repositories
             (id, name, path, default_branch, runtime, added_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            repo_id,
            repo_info["name"],
            repo_info["path"],
            repo_info.get("default_branch", "main"),
            repo_info.get("runtime", "unknown"),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    await db.commit()
    return {"id": repo_id, "name": repo_info["name"], "path": repo_info["path"]}


# ── Database dependency ────────────────────────────────────────────────────────

async def get_db():
    """FastAPI dependency: yield an aiosqlite connection for the request lifetime."""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        yield db


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


# ── Repo registration endpoints ────────────────────────────────────────────────

class _RegisterRepoRequest(BaseModel):
    path: str


@app.get("/api/repos")
async def list_repos(db=Depends(get_db)):
    """List all registered repos (simple DB query, no scan)."""
    cursor = await db.execute(
        "SELECT id, name, path, runtime, default_branch, added_at FROM repositories"
    )
    cols = [d[0] for d in cursor.description]
    rows = await cursor.fetchall()
    return {"repos": [dict(zip(cols, row)) for row in rows]}


@app.post("/api/repos")
async def register_repos(body: _RegisterRepoRequest, db=Depends(get_db)):
    """Discover git repos under the given path and register them.

    Accepts: {"path": "/some/dir"}
    Returns: {"registered": N, "repos": [{id, name, path}, ...]}

    Idempotent — re-registering the same directory doesn't create duplicates.
    """
    try:
        root = Path(body.path).expanduser().resolve()
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid path: {e}")

    if not root.exists() or not root.is_dir():
        raise HTTPException(status_code=400, detail=f"Path not found or not a directory: {body.path}")

    discovered = await discover_repos(root)

    registered: list = []
    for repo_info in discovered:
        repo_path = Path(repo_info["path"])
        repo_info["runtime"] = detect_runtime(repo_path)
        repo_info["default_branch"] = await get_default_branch(repo_path)
        result = await register_repo(db, repo_info)
        registered.append(result)

    return {"registered": len(registered), "repos": registered}


@app.delete("/api/repos/{repo_id}", status_code=204)
async def delete_repo(repo_id: str, db=Depends(get_db)):
    """Remove a repo and all its cascading data. Returns 204 on success, 404 if not found."""
    cursor = await db.execute("SELECT id FROM repositories WHERE id = ?", (repo_id,))
    row = await cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Repo not found")

    await db.execute("DELETE FROM repositories WHERE id = ?", (repo_id,))
    await db.commit()
    return Response(status_code=204)


# ── Fleet API ─────────────────────────────────────────────────────────────────

@app.get("/api/fleet")
async def get_fleet(db=Depends(get_db)):
    """Quick-scan all registered repos and return the fleet overview.

    Runs up to 8 scans in parallel (asyncio.Semaphore(8)), upserts working_state,
    and returns per-repo data with placeholder values for fields populated by
    later packets (sparkline, dep_summary, branch_count, stale_branch_count).
    """
    results = await scan_fleet_quick(db)

    # Augment with placeholder fields (populated by later packets)
    for repo in results:
        repo.setdefault("branch_count", 0)
        repo.setdefault("stale_branch_count", 0)
        repo.setdefault("dep_summary", None)
        repo.setdefault("sparkline", [])

    kpis = {
        "total_repos": len(results),
        "repos_with_changes": sum(1 for r in results if r.get("has_uncommitted")),
        "commits_this_week": 0,    # populated by packet 06
        "commits_this_month": 0,   # populated by packet 06
        "net_lines_this_week": 0,  # populated by packet 06
        "stale_branches": 0,       # populated by packet 07
        "vulnerable_deps": 0,      # populated by packet 16
        "outdated_deps": 0,        # populated by packet 16
    }

    return {
        "repos": results,
        "kpis": kpis,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
    }


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

    if args.scan:
        scan_path = Path(args.scan).expanduser().resolve()
        if not scan_path.is_dir():
            print(f"Warning: --scan path does not exist or is not a directory: {args.scan}", file=sys.stderr)
        else:
            async def _startup_scan():
                async with aiosqlite.connect(str(DB_PATH)) as db:
                    repos = await discover_repos(scan_path)
                    for repo_info in repos:
                        repo_path = Path(repo_info["path"])
                        repo_info["runtime"] = detect_runtime(repo_path)
                        repo_info["default_branch"] = await get_default_branch(repo_path)
                        await register_repo(db, repo_info)
                    print(f"Registered {len(repos)} repos from {args.scan}", flush=True)

            asyncio.run(_startup_scan())

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
