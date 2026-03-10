#!/usr/bin/env python3
"""Git Fleet — multi-repo git dashboard.

Usage:
    python git_dashboard.py [--port N] [--no-browser] [--scan PATH] [--yes|-y]
"""

# ── stdlib-only imports (safe before bootstrap) ───────────────────────────────
import asyncio
import hashlib
import json
import logging
import os
import re
import sys
import shutil
import socket
import signal
import argparse
import sqlite3
import subprocess
import urllib.request
import urllib.error
import webbrowser
from datetime import datetime, timezone, timedelta
from pathlib import Path
from threading import Timer
from typing import Literal

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

logger = logging.getLogger("git_dashboard")


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
from fastapi.responses import HTMLResponse, Response, StreamingResponse  # noqa: E402
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


# ── Git Full History Scan (packet 06) ─────────────────────────────────────────

_SHORTSTAT_RE = re.compile(
    r'(\d+) files? changed'
    r'(?:, (\d+) insertions?\(\+\))?'
    r'(?:, (\d+) deletions?\(-\))?'
)


def parse_git_log(output: str) -> list:
    """Parse 'git log --all --format=%H%x00%aI%x00%an%x00%s --shortstat' output.

    Each commit produces a dict with:
      hash, date, author, subject, insertions, deletions, files_changed.

    Merge commits (no shortstat) get 0 for numeric fields.
    """
    if not output:
        return []

    commits = []
    pending = None  # dict for the commit whose shortstat we are waiting for

    for line in output.splitlines():
        if "\x00" in line:
            # New format line — flush any pending commit first (it had no shortstat)
            if pending is not None:
                commits.append(pending)
            parts = line.split("\x00", 3)
            pending = {
                "hash": parts[0] if len(parts) > 0 else "",
                "date": parts[1] if len(parts) > 1 else "",
                "author": parts[2] if len(parts) > 2 else "",
                "subject": parts[3] if len(parts) > 3 else "",
                "insertions": 0,
                "deletions": 0,
                "files_changed": 0,
            }
        elif pending is not None:
            m = _SHORTSTAT_RE.search(line)
            if m:
                pending["files_changed"] = int(m.group(1))
                pending["insertions"] = int(m.group(2)) if m.group(2) else 0
                pending["deletions"] = int(m.group(3)) if m.group(3) else 0
                commits.append(pending)
                pending = None
            # blank lines between format line and shortstat are skipped silently

    # Flush trailing commit with no shortstat (e.g., merge commit at end of output)
    if pending is not None:
        commits.append(pending)

    return commits


def aggregate_daily_stats(commits: list) -> dict:
    """Group commits by YYYY-MM-DD and sum commits, insertions, deletions, files_changed."""
    daily = {}
    for c in commits:
        day = c["date"][:10]  # YYYY-MM-DD from ISO 8601 (safe regardless of timezone offset)
        if day not in daily:
            daily[day] = {"commits": 0, "insertions": 0, "deletions": 0, "files_changed": 0}
        daily[day]["commits"] += 1
        daily[day]["insertions"] += c["insertions"]
        daily[day]["deletions"] += c["deletions"]
        daily[day]["files_changed"] += c["files_changed"]
    return daily


async def scan_full_history(repo_path: str, since: str | None = None) -> list:
    """Run git log --all --shortstat for repo_path and return parsed commits.

    When since is provided, appends --after={since} for incremental scanning.
    """
    cmd = [
        "log",
        "--all",
        "--format=%H%x00%aI%x00%an%x00%s",
        "--shortstat",
    ]
    if since is not None:
        cmd.append(f"--after={since}")

    stdout, _stderr, _rc = await run_git(repo_path, *cmd)
    return parse_git_log(stdout)


async def upsert_daily_stats(db, repo_id: str, daily_data: dict) -> None:
    """Write aggregated daily stats to daily_stats table using INSERT OR REPLACE.

    All rows are written in a single transaction to prevent partial writes.
    """
    if not daily_data:
        return
    await db.executemany(
        """
        INSERT OR REPLACE INTO daily_stats (repo_id, date, commits, insertions, deletions, files_changed)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (repo_id, date, v["commits"], v["insertions"], v["deletions"], v["files_changed"])
            for date, v in daily_data.items()
        ],
    )
    await db.commit()


async def compute_sparklines(db) -> dict:
    """Bulk-compute 13-week commit sparklines for all repos.

    Returns a dict mapping repo_id to a list of 13 integers (index 0 = oldest week).
    Repos with no data in the 91-day window are absent from the dict.
    """
    import datetime as _dt
    today = _dt.date.today()
    start = today - _dt.timedelta(days=90)  # inclusive 91-day window

    cursor = await db.execute(
        "SELECT repo_id, date, commits FROM daily_stats WHERE date >= ?",
        (start.isoformat(),),
    )
    rows = await cursor.fetchall()

    sparklines: dict = {}
    for row in rows:
        repo_id, date_str, commits = row[0], row[1], row[2]
        d = _dt.date.fromisoformat(date_str)
        week_idx = min((d - start).days // 7, 12)
        if week_idx < 0:
            continue
        if repo_id not in sparklines:
            sparklines[repo_id] = [0] * 13
        sparklines[repo_id][week_idx] += int(commits)

    return sparklines


async def run_full_history_scan(db, repo_id: str, repo_path: str) -> int:
    """Orchestrate a full history scan for one repo.

    Reads last_full_scan_at from DB (used as --after for incremental scan),
    runs scan_full_history, aggregates, upserts daily_stats, and updates
    last_full_scan_at. Returns count of commits parsed.
    """
    cursor = await db.execute(
        "SELECT last_full_scan_at FROM repositories WHERE id = ?",
        (repo_id,),
    )
    row = await cursor.fetchone()
    since = row[0] if row else None

    commits = await scan_full_history(repo_path, since=since)
    daily_data = aggregate_daily_stats(commits)
    await upsert_daily_stats(db, repo_id, daily_data)

    await db.execute(
        "UPDATE repositories SET last_full_scan_at = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), repo_id),
    )
    await db.commit()

    return len(commits)


# ── Branch Scan ───────────────────────────────────────────────────────────────

STALE_THRESHOLD_DAYS = 30


def _is_stale(commit_date_str: str | None) -> bool:
    """Return True if commit_date_str is more than STALE_THRESHOLD_DAYS ago (or missing/invalid)."""
    if not commit_date_str:
        return True  # unknown date → treat as stale
    try:
        commit_date = datetime.fromisoformat(commit_date_str)
        cutoff = datetime.now(timezone.utc) - timedelta(days=STALE_THRESHOLD_DAYS)
        return commit_date < cutoff
    except (ValueError, TypeError):
        return True


def parse_branches(output: str, default_branch: str) -> list[dict]:
    """Parse output from git branch --format='%(refname:short)%x00%(committerdate:iso-strict)'.

    Each line produces a dict with:
      name, last_commit_date (ISO 8601 or None), is_default, is_stale.

    Empty input returns an empty list. Branch names with slashes are handled
    correctly because the null-byte delimiter avoids ambiguity.
    """
    if not output:
        return []

    branches = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue

        # Each line is: name\x00date (null-byte separated)
        if "\x00" in line:
            name, date_str = line.split("\x00", 1)
            date_str = date_str.strip() or None
        else:
            # No null byte — branch has no committer date (orphan branch or git quirk)
            name = line
            date_str = None

        name = name.strip()
        if not name:
            continue

        branches.append({
            "name": name,
            "last_commit_date": date_str,
            "is_default": name == default_branch,
            "is_stale": _is_stale(date_str),
        })

    return branches


async def scan_branches(repo_path: str, default_branch: str) -> list[dict]:
    """Run git branch command and return parsed branch list.

    Uses %(refname:short)%x00%(committerdate:iso-strict) format so branch names
    containing slashes are not ambiguous with the field separator.
    """
    stdout, _stderr, _rc = await run_git(
        repo_path,
        "branch",
        "--format=%(refname:short)%x00%(committerdate:iso-strict)",
    )
    return parse_branches(stdout, default_branch)


async def upsert_branches(db, repo_id: str, branches: list[dict]) -> None:
    """Write branch data to branches table using DELETE+INSERT in a single transaction.

    Handles branch renames and deletions by fully replacing the set for the repo.
    INSERT OR REPLACE is not used because it would not remove branches that no
    longer exist in git.
    """
    await db.execute("DELETE FROM branches WHERE repo_id = ?", (repo_id,))
    if branches:
        await db.executemany(
            "INSERT INTO branches (repo_id, name, last_commit_date, is_default, is_stale) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (repo_id, b["name"], b["last_commit_date"], b["is_default"], b["is_stale"])
                for b in branches
            ],
        )
    await db.commit()


async def run_branch_scan(db, repo_id: str, repo_path: str) -> int:
    """Orchestrate a single-repo branch scan.

    Reads default_branch from the repositories table, calls scan_branches,
    upserts the result, and returns the count of branches parsed.
    """
    cursor = await db.execute(
        "SELECT default_branch FROM repositories WHERE id = ?",
        (repo_id,),
    )
    row = await cursor.fetchone()
    default_branch = row[0] if row else "main"

    branches = await scan_branches(repo_path, default_branch)
    await upsert_branches(db, repo_id, branches)
    return len(branches)


# ── Full Scan Orchestration & SSE (packet 08) ──────────────────────────────────

# Module-level scan state
_active_scan_id: int | None = None       # Non-None while a scan is running
_scan_queues: dict = {}                  # scan_id -> asyncio.Queue (SSE bridge)
_scan_task = None                        # asyncio.Task reference (prevents GC)


async def emit_scan_progress(scan_id: int, event: dict) -> None:
    """Put a progress event onto the SSE queue for scan_id, if a listener exists."""
    q = _scan_queues.get(scan_id)
    if q:
        await q.put(event)


async def run_dep_scan_for_repo(db, repo_id: str, repo_path: str) -> None:
    """Detect, parse, and health-check deps for one repo, then persist to DB."""
    repo_path_obj = Path(repo_path)

    # 1. Parse raw deps from manifest files
    raw_deps = parse_deps_for_repo(repo_path_obj)
    if not raw_deps:
        # Clear any stale deps if manifest was removed
        await db.execute("DELETE FROM dependencies WHERE repo_id = ?", (repo_id,))
        await db.commit()
        return

    # 2. Route through ecosystem health checkers (each operates on the full list;
    #    only enriches deps matching its ecosystem)
    enriched = list(raw_deps)
    try:
        enriched = check_python_deps(repo_path_obj, enriched)
    except Exception as exc:
        logger.error("Python dep check failed for %s: %s", repo_id, exc)
    try:
        enriched = check_node_deps(repo_path_obj, enriched)
    except Exception as exc:
        logger.error("Node dep check failed for %s: %s", repo_id, exc)
    try:
        enriched = check_go_deps(repo_path_obj, enriched)
    except Exception as exc:
        logger.error("Go dep check failed for %s: %s", repo_id, exc)
    try:
        enriched = check_rust_deps(repo_path_obj, enriched)
    except Exception as exc:
        logger.error("Rust dep check failed for %s: %s", repo_id, exc)
    try:
        enriched = check_ruby_deps(repo_path_obj, enriched)
    except Exception as exc:
        logger.error("Ruby dep check failed for %s: %s", repo_id, exc)
    try:
        enriched = check_php_deps(repo_path_obj, enriched)
    except Exception as exc:
        logger.error("PHP dep check failed for %s: %s", repo_id, exc)

    # 3. Upsert into dependencies table
    for dep in enriched:
        await db.execute(
            """INSERT OR REPLACE INTO dependencies
               (repo_id, manager, name, current_version, wanted_version,
                latest_version, severity, advisory_id, checked_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                repo_id,
                dep.get("manager", ""),
                dep.get("name", ""),
                dep.get("current_version"),
                dep.get("wanted_version"),
                dep.get("latest_version"),
                dep.get("severity", "ok"),
                dep.get("advisory_id"),
                dep.get("checked_at"),
            ),
        )

    # 4. Delete stale deps (in DB but no longer in manifest)
    current_keys = {(dep.get("manager", ""), dep.get("name", "")) for dep in enriched}
    cursor = await db.execute(
        "SELECT manager, name FROM dependencies WHERE repo_id = ?", (repo_id,)
    )
    db_keys = await cursor.fetchall()
    for manager, name in db_keys:
        if (manager, name) not in current_keys:
            await db.execute(
                "DELETE FROM dependencies WHERE repo_id = ? AND manager = ? AND name = ?",
                (repo_id, manager, name),
            )

    await db.commit()


async def run_fleet_scan(scan_id: int, scan_type: str) -> None:
    """Background task: iterate all repos sequentially and scan each one.

    For scan_type="full": runs run_full_history_scan, run_branch_scan, and
        run_dep_scan_for_repo per repo.
    For scan_type="deps": runs run_dep_scan_for_repo per repo.

    Emits SSE progress events after each repo. Updates scan_log throughout.
    Clears _active_scan_id in finally, even on crash.
    """
    global _active_scan_id
    try:
        async with aiosqlite.connect(str(DB_PATH)) as db:
            if scan_type == "deps":
                # Iterate all repos sequentially, running dep scans only
                cursor = await db.execute("SELECT id, name, path FROM repositories")
                repos = await cursor.fetchall()
                total = len(repos)
                scanned = 0

                for i, (repo_id, name, repo_path) in enumerate(repos):
                    try:
                        await run_dep_scan_for_repo(db, repo_id, repo_path)
                        scanned += 1
                    except Exception as exc:
                        logger.error("Dep scan failed for %s: %s", name, exc)

                    await emit_scan_progress(scan_id, {
                        "repo": name,
                        "step": "deps",
                        "progress": i + 1,
                        "total": total,
                        "status": "scanning",
                    })
                    await db.execute(
                        "UPDATE scan_log SET repos_scanned = ? WHERE id = ?",
                        (scanned, scan_id),
                    )
                    await db.commit()

                # Determine final status
                if total == 0 or scanned > 0:
                    status = "completed"
                else:
                    status = "failed"

                finished_at = datetime.now(timezone.utc).isoformat()
                await db.execute(
                    "UPDATE scan_log SET status = ?, finished_at = ?, repos_scanned = ? WHERE id = ?",
                    (status, finished_at, scanned, scan_id),
                )
                await db.commit()

                await emit_scan_progress(scan_id, {
                    "progress": total,
                    "total": total,
                    "status": status,
                })
                return

            # type == "full": iterate repos sequentially
            cursor = await db.execute("SELECT id, name, path FROM repositories")
            repos = await cursor.fetchall()
            total = len(repos)
            scanned = 0

            for i, (repo_id, name, repo_path) in enumerate(repos):
                try:
                    await run_full_history_scan(db, repo_id, repo_path)
                    await run_branch_scan(db, repo_id, repo_path)
                    await run_dep_scan_for_repo(db, repo_id, repo_path)
                    scanned += 1
                except Exception as exc:
                    logger.error("Scan failed for %s: %s", name, exc)

                await emit_scan_progress(scan_id, {
                    "repo": name,
                    "step": "deps",
                    "progress": i + 1,
                    "total": total,
                    "status": "scanning",
                })
                await db.execute(
                    "UPDATE scan_log SET repos_scanned = ? WHERE id = ?",
                    (scanned, scan_id),
                )
                await db.commit()

            # Determine final status
            # Empty fleet or ≥1 success → completed; all repos failed → failed
            if total == 0 or scanned > 0:
                status = "completed"
            else:
                status = "failed"

            finished_at = datetime.now(timezone.utc).isoformat()
            await db.execute(
                "UPDATE scan_log SET status = ?, finished_at = ?, repos_scanned = ? WHERE id = ?",
                (status, finished_at, scanned, scan_id),
            )
            await db.commit()

            await emit_scan_progress(scan_id, {
                "progress": total,
                "total": total,
                "status": status,
            })
    finally:
        _active_scan_id = None


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


# ── Dependency Detection & Parsing (packet 12) ────────────────────────────────

try:
    import tomllib  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]

# Detection priority table: (filename, manager, runtime)
# Within a runtime, only the highest-priority file is returned.
_DEP_FILE_PRIORITY: list[tuple[str, str, str]] = [
    ("pyproject.toml", "pip",      "python"),
    ("requirements.txt", "pip",    "python"),
    ("package.json",   "npm",      "node"),
    ("go.mod",         "gomod",    "go"),
    ("Cargo.toml",     "cargo",    "rust"),
    ("Gemfile",        "bundler",  "ruby"),
    ("composer.json",  "composer", "php"),
]


def detect_dep_files(repo_path: Path) -> list[dict]:
    """Return a list of {file, manager, runtime} for every manifest found in repo_path.

    Within the same runtime, only the highest-priority file is returned.
    Across different runtimes, all detected files are returned.
    Order matches the detection priority table.
    """
    try:
        dir_files = {p.name.lower() for p in repo_path.iterdir() if p.is_file()}
    except (OSError, PermissionError):
        return []

    seen_runtimes: set[str] = set()
    results: list[dict] = []
    for filename, manager, runtime in _DEP_FILE_PRIORITY:
        if filename.lower() in dir_files and runtime not in seen_runtimes:
            seen_runtimes.add(runtime)
            results.append({"file": filename, "manager": manager, "runtime": runtime})
    return results


def parse_requirements_txt(file_path: Path, _visited: set[str] | None = None) -> list[dict]:
    """Parse a requirements.txt file and return [{name, version, manager}].

    Handles:
    - Comments and blank lines (skip)
    - -e / --editable (skip)
    - -r / --requirement includes (one level, circular-safe)
    - Other flags (-i, --index-url, etc.) (skip)
    - name==version (exact pin → extract version)
    - name>=version or unpinned (version = None)
    """
    if _visited is None:
        _visited = set()

    resolved = str(file_path.resolve())
    if resolved in _visited:
        return []
    _visited.add(resolved)

    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError):
        return []

    deps: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-e") or line.startswith("--editable"):
            continue
        if line.startswith("-r") or line.startswith("--requirement"):
            # Extract the included file path
            parts = line.split(None, 1)
            if len(parts) < 2:
                continue
            include_path = file_path.parent / parts[1].strip()
            deps.extend(parse_requirements_txt(include_path, _visited))
            continue
        if line.startswith("-"):
            # Other flags: -i, --index-url, -f, --find-links, etc.
            continue

        # Package line: may have extras [extra], env markers ; marker
        # Strip environment markers
        pkg_part = line.split(";")[0].strip()
        # Strip inline comments
        pkg_part = pkg_part.split(" #")[0].strip()

        # Match: name[extras]  op  version
        m = re.match(
            r"^([A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?)"  # package name
            r"(\[[^\]]*\])?"                                   # optional extras
            r"\s*==\s*([^\s,;]+)",                             # == version
            pkg_part,
        )
        if m:
            deps.append({"name": m.group(1), "version": m.group(4), "manager": "pip"})
            continue

        # Unpinned or range constraint — just extract the name
        m2 = re.match(
            r"^([A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?)(\[[^\]]*\])?",
            pkg_part,
        )
        if m2:
            deps.append({"name": m2.group(1), "version": None, "manager": "pip"})

    return deps


def parse_pyproject_toml(file_path: Path) -> list[dict]:
    """Parse pyproject.toml and return [{name, version, manager}].

    Supports:
    - PEP 621: [project].dependencies  (preferred if both sections exist)
    - Poetry:  [tool.poetry.dependencies]
    """
    if tomllib is None:
        logger.warning("tomllib unavailable; skipping TOML parsing for %s", file_path)
        return []
    try:
        with open(file_path, "rb") as f:
            data = tomllib.load(f)
    except Exception as exc:
        logger.warning("Failed to parse %s: %s", file_path, exc)
        return []

    deps: list[dict] = []

    # PEP 621 takes priority
    project_deps = data.get("project", {}).get("dependencies", None)
    if project_deps is not None:
        for entry in project_deps:
            if not isinstance(entry, str):
                continue
            # Strip markers
            entry = entry.split(";")[0].strip()
            m = re.match(
                r"^([A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?)(\[[^\]]*\])?"
                r"\s*==\s*([^\s,;]+)",
                entry,
            )
            if m:
                deps.append({"name": m.group(1), "version": m.group(4), "manager": "pip"})
            else:
                m2 = re.match(
                    r"^([A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?)(\[[^\]]*\])?",
                    entry,
                )
                if m2:
                    deps.append({"name": m2.group(1), "version": None, "manager": "pip"})
        return deps

    # Poetry fallback
    poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", None)
    if poetry_deps is not None:
        for name, val in poetry_deps.items():
            if isinstance(val, str):
                version = val if val != "*" else None
            elif isinstance(val, dict):
                version = val.get("version") or None
            else:
                version = None
            deps.append({"name": name, "version": version, "manager": "pip"})
        return deps

    return []


def parse_package_json(file_path: Path) -> list[dict]:
    """Parse package.json and return [{name, version, manager}] for all deps."""
    try:
        data = json.loads(file_path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        logger.warning("Failed to parse %s: %s", file_path, exc)
        return []

    deps: list[dict] = []
    for section in ("dependencies", "devDependencies"):
        section_data = data.get(section, {})
        if not isinstance(section_data, dict):
            continue
        for name, version in section_data.items():
            deps.append({"name": name, "version": version if isinstance(version, str) else None, "manager": "npm"})
    return deps


def parse_go_mod(file_path: Path) -> list[dict]:
    """Parse go.mod and return [{name, version, manager}].

    Handles both require (...) blocks and single-line require statements.
    Indirect deps are included. Strips // indirect comments.
    """
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError):
        return []

    deps: list[dict] = []
    in_require_block = False

    for line in text.splitlines():
        stripped = line.strip()

        if stripped.startswith("require ("):
            in_require_block = True
            continue
        if in_require_block:
            if stripped == ")":
                in_require_block = False
                continue
            # Strip inline comments (e.g., "// indirect")
            stripped = re.sub(r"\s*//.*$", "", stripped).strip()
            if not stripped:
                continue
            parts = stripped.split()
            if len(parts) >= 2:
                deps.append({"name": parts[0], "version": parts[1], "manager": "gomod"})
            continue

        # Single-line: "require module/path vX.Y.Z"
        m = re.match(r"^require\s+(\S+)\s+(\S+)", stripped)
        if m:
            deps.append({"name": m.group(1), "version": m.group(2), "manager": "gomod"})

    return deps


def parse_cargo_toml(file_path: Path) -> list[dict]:
    """Parse Cargo.toml and return [{name, version, manager}].

    Reads [dependencies] and [dev-dependencies].
    Handles string values ("1.0") and table values ({version = "1.0", ...}).
    """
    if tomllib is None:
        logger.warning("tomllib unavailable; skipping TOML parsing for %s", file_path)
        return []
    try:
        with open(file_path, "rb") as f:
            data = tomllib.load(f)
    except Exception as exc:
        logger.warning("Failed to parse %s: %s", file_path, exc)
        return []

    deps: list[dict] = []
    for section in ("dependencies", "dev-dependencies"):
        section_data = data.get(section, {})
        if not isinstance(section_data, dict):
            continue
        for name, val in section_data.items():
            if isinstance(val, str):
                version = val
            elif isinstance(val, dict):
                version = val.get("version") or None
            else:
                version = None
            deps.append({"name": name, "version": version, "manager": "cargo"})
    return deps


def parse_gemfile(file_path: Path) -> list[dict]:
    """Parse Gemfile and return [{name, version, manager}].

    Matches: gem 'name' and gem 'name', 'version_constraint'
    Also handles double-quoted gem names.
    """
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError):
        return []

    deps: list[dict] = []
    # Match: gem 'name' or gem 'name', 'version'  (single or double quotes)
    pattern = re.compile(r"""gem\s+['"]([^'"]+)['"]\s*(?:,\s*['"]([^'"]+)['"])?""")
    for m in pattern.finditer(text):
        name = m.group(1)
        version = m.group(2) if m.group(2) else None
        deps.append({"name": name, "version": version, "manager": "bundler"})
    return deps


def parse_composer_json(file_path: Path) -> list[dict]:
    """Parse composer.json and return [{name, version, manager}].

    Reads require and require-dev. Skips php and ext-* platform requirements.
    """
    try:
        data = json.loads(file_path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        logger.warning("Failed to parse %s: %s", file_path, exc)
        return []

    deps: list[dict] = []
    for section in ("require", "require-dev"):
        section_data = data.get(section, {})
        if not isinstance(section_data, dict):
            continue
        for name, version in section_data.items():
            # Skip platform requirements
            if name == "php" or name.startswith("ext-"):
                continue
            deps.append({
                "name": name,
                "version": version if isinstance(version, str) else None,
                "manager": "composer",
            })
    return deps


def parse_deps_for_repo(repo_path: Path) -> list[dict]:
    """Detect manifest files in repo_path and parse all found ecosystems.

    Returns a merged list of {name, version, manager} dicts.
    Within the same runtime, only the highest-priority manifest is parsed.
    """
    manifest_entries = detect_dep_files(repo_path)
    if not manifest_entries:
        return []

    _parser_map = {
        "requirements.txt": parse_requirements_txt,
        "pyproject.toml":   parse_pyproject_toml,
        "package.json":     parse_package_json,
        "go.mod":           parse_go_mod,
        "Cargo.toml":       parse_cargo_toml,
        "Gemfile":          parse_gemfile,
        "composer.json":    parse_composer_json,
    }

    all_deps: list[dict] = []
    for entry in manifest_entries:
        filename = entry["file"]
        parser = _parser_map.get(filename)
        if parser is None:
            continue
        file_path = repo_path / filename
        try:
            parsed = parser(file_path)
        except Exception as exc:
            logger.warning("Error parsing %s in %s: %s", filename, repo_path, exc)
            parsed = []
        all_deps.extend(parsed)
    return all_deps


# ── Python dependency health (Packet 13) ──────────────────────────────────────

def classify_severity(current: str, latest: str) -> str:
    """Compare two PEP 440 version strings and return a severity label.

    Returns:
        "ok"       — current >= latest (up-to-date or ahead)
        "major"    — different major version (latest has higher major)
        "outdated" — same major, any other version difference
    """
    from packaging.version import parse as parse_version  # noqa: PLC0415

    cur = parse_version(current)
    lat = parse_version(latest)
    if cur >= lat:
        return "ok"
    if cur.major != lat.major:
        return "major"
    return "outdated"


def check_python_outdated(deps: list[dict]) -> list[dict]:
    """Query PyPI JSON API for each pinned pip dep and populate version/severity fields.

    Skips deps where:
      - manager != "pip"
      - version is None
      - version contains range operators (>=, ~=, <, !=, >, ^)

    On any network or parse error the dep is left with severity="ok" and
    latest_version=None (fail-open: don't block the rest of the scan).

    Returns a new list of dicts (input dicts are copied, not mutated in-place).
    """
    _RANGE_OPS = (">=", "<=", "~=", "!=", ">", "<", "^", "*")

    result: list[dict] = []
    for dep in deps:
        d = dict(dep)  # shallow copy; only add new scalar fields
        if d.get("manager") != "pip" or d.get("version") is None:
            result.append(d)
            continue

        ver_str: str = d["version"]

        # Extract bare version from "name==version" or "==version" notation
        if "==" in ver_str:
            ver_str = ver_str.split("==")[-1].strip()

        # Skip range/unpinned specifiers
        if any(op in ver_str for op in _RANGE_OPS):
            result.append(d)
            continue

        name = d["name"]
        latest_version = None
        severity = "ok"
        try:
            url = f"https://pypi.org/pypi/{name}/json"
            with urllib.request.urlopen(url, timeout=15) as resp:
                data = json.loads(resp.read())
            latest_version = data["info"]["version"]
            severity = classify_severity(ver_str, latest_version)
        except Exception as exc:
            logger.warning("PyPI lookup failed for %s: %s", name, exc)

        d["latest_version"] = latest_version
        d["severity"] = severity
        result.append(d)

    return result


def check_python_vulns(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Run pip-audit against the repo's requirements.txt (if present) and merge results.

    If pip-audit is not installed (TOOLS["pip_audit"] is None), returns deps unchanged.
    If the repo has no requirements.txt (only pyproject.toml), logs a warning and skips.
    On any subprocess or parse failure, returns deps unchanged (fail-open).

    Vulnerability severity overrides any prior severity (vuln > major > outdated > ok).
    Sets dep["severity"] = "vulnerable" and dep["advisory_id"] = <first vuln ID>.
    """
    pip_audit = TOOLS.get("pip_audit")
    if not pip_audit:
        return deps

    # pip-audit --requirement only works with requirements.txt-style files
    manifest = repo_path / "requirements.txt"
    if not manifest.exists():
        logger.warning(
            "check_python_vulns: no requirements.txt in %s — skipping vuln check", repo_path
        )
        return deps

    try:
        proc = subprocess.run(
            [pip_audit, "--requirement", str(manifest), "--format", "json"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        raw = json.loads(proc.stdout)
    except Exception as exc:
        logger.warning("pip-audit failed for %s: %s", repo_path, exc)
        return deps

    # Build lookup: {package_name_lower: first_vuln_id}
    vuln_map: dict[str, str] = {}
    try:
        for entry in raw.get("dependencies", []):
            vuln_list = entry.get("vulns", [])
            if vuln_list:
                vuln_map[entry["name"].lower()] = vuln_list[0]["id"]
    except Exception as exc:
        logger.warning("pip-audit output parse error for %s: %s", repo_path, exc)
        return deps

    result: list[dict] = []
    for dep in deps:
        d = dict(dep)
        key = d.get("name", "").lower()
        if key in vuln_map:
            d["severity"] = "vulnerable"
            d["advisory_id"] = vuln_map[key]
        result.append(d)
    return result


def check_python_deps(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Orchestrate outdated + vuln checks for pip deps in a repo.

    1. Splits deps into pip and non-pip groups.
    2. Runs check_python_outdated on pip deps.
    3. Runs check_python_vulns on pip deps (merges vuln severity).
    4. Stamps required health fields on all pip deps (fills defaults for skipped deps).
    5. Returns merged list (pip enriched + non-pip unchanged).
    """
    if not deps:
        return []

    pip_deps = [d for d in deps if d.get("manager") == "pip"]
    other_deps = [d for d in deps if d.get("manager") != "pip"]

    if not pip_deps:
        return other_deps

    pip_deps = check_python_outdated(pip_deps)
    pip_deps = check_python_vulns(repo_path, pip_deps)

    # Ensure all required fields are present (fill defaults for skipped/unpinned deps)
    now = datetime.now(timezone.utc).isoformat()
    enriched: list[dict] = []
    for dep in pip_deps:
        d = dict(dep)
        ver = d.get("version")
        d.setdefault("current_version", ver)
        d.setdefault("wanted_version", ver)
        d.setdefault("latest_version", None)
        d.setdefault("severity", "ok")
        d.setdefault("advisory_id", None)
        d.setdefault("checked_at", now)
        enriched.append(d)

    return enriched + other_deps


# ── Node dependency health (Packet 14) ────────────────────────────────────────


def check_node_outdated(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Run npm outdated --json and enrich each npm dep with version/severity fields.

    If npm is not available (TOOLS["npm"] is None), returns deps unchanged.
    Handles npm's non-zero exit code when outdated packages exist (this is normal).
    On any subprocess or JSON parse failure, returns deps unchanged (fail-open).
    """
    npm = TOOLS.get("npm")
    if not npm:
        return deps

    now = datetime.now(timezone.utc).isoformat()

    try:
        proc = subprocess.run(
            [npm, "outdated", "--json"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=120,
        )
        # npm outdated exits with code 1 when outdated packages exist — this is normal.
        # Only treat as error if stdout is empty/unparseable and returncode is non-zero.
        if not proc.stdout.strip() and proc.returncode != 0:
            logger.warning("npm outdated returned no output for %s (rc=%d)", repo_path, proc.returncode)
            return deps
        outdated_map = json.loads(proc.stdout)
    except subprocess.CalledProcessError as exc:
        logger.warning("npm outdated CalledProcessError for %s: %s", repo_path, exc)
        return deps
    except Exception as exc:
        logger.warning("npm outdated failed for %s: %s", repo_path, exc)
        return deps

    result: list[dict] = []
    for dep in deps:
        d = dict(dep)
        name = d.get("name", "")
        if name in outdated_map:
            info = outdated_map[name]
            d["current_version"] = info.get("current")
            d["wanted_version"] = info.get("wanted")
            d["latest_version"] = info.get("latest")
            current = info.get("current") or ""
            latest = info.get("latest") or ""
            if current and latest:
                d["severity"] = classify_severity(current, latest)
            else:
                d["severity"] = "outdated"
        else:
            # Not in npm outdated output → up to date
            d.setdefault("current_version", d.get("version"))
            d.setdefault("wanted_version", d.get("version"))
            d.setdefault("latest_version", None)
            d["severity"] = "ok"
        d["checked_at"] = now
        result.append(d)

    return result


def check_node_vulns(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Run npm audit --json and merge vulnerability info into dep dicts.

    If npm is not available (TOOLS["npm"] is None), returns deps unchanged.
    Handles npm's non-zero exit code when vulnerabilities exist (normal behavior).
    If npm audit fails (e.g. missing package-lock.json), returns deps unchanged (fail-open).
    Vulnerability severity overrides any prior severity (vuln > major > outdated > ok).
    Sets dep["severity"] = "vulnerable" and dep["advisory_id"] = "npm:<name>".
    """
    npm = TOOLS.get("npm")
    if not npm:
        return deps

    try:
        proc = subprocess.run(
            [npm, "audit", "--json"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if not proc.stdout.strip():
            logger.warning("npm audit returned no output for %s (rc=%d)", repo_path, proc.returncode)
            return deps
        raw = json.loads(proc.stdout)
    except subprocess.CalledProcessError as exc:
        logger.warning("npm audit CalledProcessError for %s: %s", repo_path, exc)
        return deps
    except Exception as exc:
        logger.warning("npm audit failed for %s: %s", repo_path, exc)
        return deps

    # Build lookup: {package_name_lower: True} for vulnerable packages
    vuln_names: set[str] = set()
    try:
        for name in raw.get("vulnerabilities", {}).keys():
            vuln_names.add(name.lower())
    except Exception as exc:
        logger.warning("npm audit output parse error for %s: %s", repo_path, exc)
        return deps

    result: list[dict] = []
    for dep in deps:
        d = dict(dep)
        name_lower = d.get("name", "").lower()
        if name_lower in vuln_names:
            d["severity"] = "vulnerable"
            d["advisory_id"] = f"npm:{d.get('name', name_lower)}"
        result.append(d)

    return result


def check_node_deps(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Orchestrate outdated + vuln checks for npm deps in a repo.

    1. Filters deps to npm-managed entries.
    2. Runs check_node_outdated on npm deps.
    3. Runs check_node_vulns on npm deps.
    4. Stamps required health fields on all npm deps (fills defaults for skipped deps).
    5. Returns merged list (npm enriched + non-npm unchanged).
    """
    if not deps:
        return []

    npm_deps = [d for d in deps if d.get("manager") == "npm"]
    other_deps = [d for d in deps if d.get("manager") != "npm"]

    if not npm_deps:
        return other_deps

    npm_deps = check_node_outdated(repo_path, npm_deps)
    npm_deps = check_node_vulns(repo_path, npm_deps)

    # Ensure all required fields are present
    now = datetime.now(timezone.utc).isoformat()
    enriched: list[dict] = []
    for dep in npm_deps:
        d = dict(dep)
        ver = d.get("version")
        d.setdefault("current_version", ver)
        d.setdefault("wanted_version", ver)
        d.setdefault("latest_version", None)
        d.setdefault("severity", "ok")
        d.setdefault("advisory_id", None)
        d.setdefault("checked_at", now)
        enriched.append(d)

    return enriched + other_deps


# ── Go dependency health (Packet 15) ──────────────────────────────────────────


def _strip_v(version: str) -> str:
    """Strip leading 'v' from Go-style version strings for packaging.version comparison."""
    return version.lstrip("v") if version else version


def _parse_go_ndjson(stdout: str) -> list[dict]:
    """Parse go list -m -u -json all NDJSON output (one JSON object per line).

    Returns a list of parsed JSON objects.
    """
    decoder = json.JSONDecoder()
    pos = 0
    results: list[dict] = []
    text = stdout.strip()
    while pos < len(text):
        remaining = text[pos:]
        stripped = remaining.lstrip()
        if not stripped:
            break
        obj, end = decoder.raw_decode(stripped)
        results.append(obj)
        pos += (len(remaining) - len(stripped)) + end
    return results


def check_go_outdated(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Run go list -m -u -json all and enrich gomod deps with version/severity fields.

    If go is not available (TOOLS["go"] is None), returns deps unchanged.
    Parses NDJSON output (one JSON object per line).
    Strips 'v' prefix from Go versions before calling classify_severity().
    On any subprocess or parse failure, returns deps unchanged (fail-open).
    """
    go = TOOLS.get("go")
    if not go:
        return deps

    try:
        proc = subprocess.run(
            [go, "list", "-m", "-u", "-json", "all"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=120,
        )
        modules = _parse_go_ndjson(proc.stdout)
    except Exception as exc:
        logger.warning("go list failed for %s: %s", repo_path, exc)
        return deps

    # Build lookup: {module_path: {"version": str, "update": str|None}}
    mod_map: dict[str, dict] = {}
    for mod in modules:
        path = mod.get("Path", "")
        version = mod.get("Version", "")
        update = mod.get("Update", {})
        update_version = update.get("Version") if update else None
        mod_map[path] = {"version": version, "update": update_version}

    result: list[dict] = []
    for dep in deps:
        d = dict(dep)
        name = d.get("name", "")
        if name in mod_map:
            info = mod_map[name]
            current = info["version"]
            update_ver = info["update"]
            d["current_version"] = current
            d["wanted_version"] = current  # Go has no "wanted" concept
            if update_ver:
                d["latest_version"] = update_ver
                d["severity"] = classify_severity(_strip_v(current), _strip_v(update_ver))
            else:
                d["latest_version"] = current
                d["severity"] = "ok"
        result.append(d)
    return result


def check_go_vulns(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Run govulncheck -json ./... and merge vulnerability info into gomod dep dicts.

    If govulncheck is not available (TOOLS["govulncheck"] is None), returns deps unchanged.
    Parses the Vulns array from govulncheck JSON output.
    Vulnerability severity overrides any prior severity.
    Sets dep["severity"] = "vulnerable" and dep["advisory_id"] = OSV ID.
    """
    govulncheck = TOOLS.get("govulncheck")
    if not govulncheck:
        return deps

    try:
        proc = subprocess.run(
            [govulncheck, "-json", "./..."],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=300,
        )
        raw = json.loads(proc.stdout)
    except Exception as exc:
        logger.warning("govulncheck failed for %s: %s", repo_path, exc)
        return deps

    # Build lookup: {module_path: osv_id}
    vuln_map: dict[str, str] = {}
    try:
        for vuln in raw.get("Vulns", []):
            osv_id = vuln.get("OSV", {}).get("id", "")
            for mod in vuln.get("Modules", []):
                mod_path = mod.get("Path", "")
                if mod_path:
                    vuln_map[mod_path] = osv_id
    except Exception as exc:
        logger.warning("govulncheck output parse error for %s: %s", repo_path, exc)
        return deps

    result: list[dict] = []
    for dep in deps:
        d = dict(dep)
        if d.get("name", "") in vuln_map:
            d["severity"] = "vulnerable"
            d["advisory_id"] = vuln_map[d["name"]]
        result.append(d)
    return result


def check_go_deps(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Orchestrate outdated + vuln checks for gomod deps in a repo.

    1. Filters deps to gomod-managed entries.
    2. Runs check_go_outdated on gomod deps.
    3. Runs check_go_vulns on gomod deps.
    4. Stamps required health fields on all gomod deps (fills defaults for skipped deps).
    5. Returns merged list (gomod enriched + non-gomod unchanged).
    """
    if not deps:
        return []

    go_deps = [d for d in deps if d.get("manager") == "gomod"]
    other_deps = [d for d in deps if d.get("manager") != "gomod"]

    if not go_deps:
        return other_deps

    go_deps = check_go_outdated(repo_path, go_deps)
    go_deps = check_go_vulns(repo_path, go_deps)

    now = datetime.now(timezone.utc).isoformat()
    enriched: list[dict] = []
    for dep in go_deps:
        d = dict(dep)
        ver = d.get("version")
        d.setdefault("current_version", ver)
        d.setdefault("wanted_version", ver)
        d.setdefault("latest_version", None)
        d.setdefault("severity", "ok")
        d.setdefault("advisory_id", None)
        d.setdefault("checked_at", now)
        enriched.append(d)

    return enriched + other_deps


# ── Rust dependency health (Packet 15) ────────────────────────────────────────


def check_rust_outdated(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Run cargo outdated --format json and enrich cargo deps with version/severity fields.

    If cargo-outdated is not available (TOOLS["cargo_outdated"] is None), returns deps unchanged.
    On any subprocess or parse failure, returns deps unchanged (fail-open).
    """
    cargo_outdated = TOOLS.get("cargo_outdated")
    if not cargo_outdated:
        return deps

    try:
        proc = subprocess.run(
            [cargo_outdated, "--format", "json"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=120,
        )
        raw = json.loads(proc.stdout)
    except Exception as exc:
        logger.warning("cargo outdated failed for %s: %s", repo_path, exc)
        return deps

    # Build lookup: {name: {"project": current, "latest": latest}}
    outdated_map: dict[str, dict] = {}
    try:
        for entry in raw.get("dependencies", []):
            name = entry.get("name", "")
            if name:
                outdated_map[name] = {
                    "project": entry.get("project", ""),
                    "latest": entry.get("latest", ""),
                }
    except Exception as exc:
        logger.warning("cargo outdated output parse error for %s: %s", repo_path, exc)
        return deps

    result: list[dict] = []
    for dep in deps:
        d = dict(dep)
        name = d.get("name", "")
        if name in outdated_map:
            info = outdated_map[name]
            current = info["project"]
            latest = info["latest"]
            d["current_version"] = current
            d["wanted_version"] = current  # cargo has no "wanted" concept
            d["latest_version"] = latest
            if current and latest:
                d["severity"] = classify_severity(current, latest)
            else:
                d["severity"] = "outdated"
        result.append(d)
    return result


def check_rust_vulns(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Run cargo audit --json and merge vulnerability info into cargo dep dicts.

    If cargo-audit is not available (TOOLS["cargo_audit"] is None), returns deps unchanged.
    Vulnerability severity overrides any prior severity.
    Sets dep["severity"] = "vulnerable" and dep["advisory_id"] = RUSTSEC ID.
    """
    cargo_audit = TOOLS.get("cargo_audit")
    if not cargo_audit:
        return deps

    try:
        proc = subprocess.run(
            [cargo_audit, "--json"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=120,
        )
        raw = json.loads(proc.stdout)
    except Exception as exc:
        logger.warning("cargo audit failed for %s: %s", repo_path, exc)
        return deps

    # Build lookup: {package_name: rustsec_id}
    vuln_map: dict[str, str] = {}
    try:
        for entry in raw.get("vulnerabilities", {}).get("list", []):
            advisory_id = entry.get("advisory", {}).get("id", "")
            pkg_name = entry.get("package", {}).get("name", "")
            if pkg_name and advisory_id:
                vuln_map[pkg_name] = advisory_id
    except Exception as exc:
        logger.warning("cargo audit output parse error for %s: %s", repo_path, exc)
        return deps

    result: list[dict] = []
    for dep in deps:
        d = dict(dep)
        if d.get("name", "") in vuln_map:
            d["severity"] = "vulnerable"
            d["advisory_id"] = vuln_map[d["name"]]
        result.append(d)
    return result


def check_rust_deps(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Orchestrate outdated + vuln checks for cargo deps in a repo.

    1. Filters deps to cargo-managed entries.
    2. Runs check_rust_outdated on cargo deps.
    3. Runs check_rust_vulns on cargo deps (cargo-audit is independent of cargo-outdated).
    4. Stamps required health fields on all cargo deps.
    5. Returns merged list (cargo enriched + non-cargo unchanged).
    """
    if not deps:
        return []

    cargo_deps = [d for d in deps if d.get("manager") == "cargo"]
    other_deps = [d for d in deps if d.get("manager") != "cargo"]

    if not cargo_deps:
        return other_deps

    cargo_deps = check_rust_outdated(repo_path, cargo_deps)
    cargo_deps = check_rust_vulns(repo_path, cargo_deps)

    now = datetime.now(timezone.utc).isoformat()
    enriched: list[dict] = []
    for dep in cargo_deps:
        d = dict(dep)
        ver = d.get("version")
        d.setdefault("current_version", ver)
        d.setdefault("wanted_version", ver)
        d.setdefault("latest_version", None)
        d.setdefault("severity", "ok")
        d.setdefault("advisory_id", None)
        d.setdefault("checked_at", now)
        enriched.append(d)

    return enriched + other_deps


# ── Ruby dependency health (Packet 15) ────────────────────────────────────────


def check_ruby_outdated(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Run bundle outdated --parseable and enrich bundler deps with version/severity fields.

    If bundle is not available (TOOLS["bundle"] is None), returns deps unchanged.
    Parses line-by-line output: 'gem-name (newest X.Y.Z, installed A.B.C, ...)'.
    On any subprocess or parse failure, returns deps unchanged (fail-open).
    """
    bundle = TOOLS.get("bundle")
    if not bundle:
        return deps

    try:
        proc = subprocess.run(
            [bundle, "outdated", "--parseable"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=120,
        )
        stdout = proc.stdout
    except Exception as exc:
        logger.warning("bundle outdated failed for %s: %s", repo_path, exc)
        return deps

    # Parse line-by-line: gem-name (newest X.Y.Z, installed A.B.C[, requested ~> A.B])
    _BUNDLE_LINE_RE = re.compile(
        r'^(\S+)\s+\(newest\s+([^,]+),\s+installed\s+([^,)]+)'
    )
    outdated_map: dict[str, dict] = {}
    for line in stdout.splitlines():
        m = _BUNDLE_LINE_RE.match(line.strip())
        if m:
            gem_name = m.group(1)
            newest = m.group(2).strip()
            installed = m.group(3).strip()
            outdated_map[gem_name] = {"installed": installed, "newest": newest}

    result: list[dict] = []
    for dep in deps:
        d = dict(dep)
        name = d.get("name", "")
        if name in outdated_map:
            info = outdated_map[name]
            current = info["installed"]
            latest = info["newest"]
            d["current_version"] = current
            d["wanted_version"] = current  # bundler has no "wanted" concept
            d["latest_version"] = latest
            d["severity"] = classify_severity(current, latest)
        result.append(d)
    return result


def check_ruby_vulns(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Run bundler-audit check --format json and merge vulnerability info.

    If bundler-audit is not available (TOOLS["bundler_audit"] is None), returns deps unchanged.
    Vulnerability severity overrides any prior severity.
    Sets dep["severity"] = "vulnerable" and dep["advisory_id"] = advisory ID.
    """
    bundler_audit = TOOLS.get("bundler_audit")
    if not bundler_audit:
        return deps

    try:
        proc = subprocess.run(
            [bundler_audit, "check", "--format", "json"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=120,
        )
        raw = json.loads(proc.stdout)
    except Exception as exc:
        logger.warning("bundler-audit failed for %s: %s", repo_path, exc)
        return deps

    # Build lookup: {gem_name_lower: advisory_id}
    vuln_map: dict[str, str] = {}
    try:
        for entry in raw.get("results", []):
            gem_name = entry.get("gem", {}).get("name", "")
            advisory_id = entry.get("advisory", {}).get("id", "")
            if gem_name and advisory_id:
                vuln_map[gem_name.lower()] = advisory_id
    except Exception as exc:
        logger.warning("bundler-audit output parse error for %s: %s", repo_path, exc)
        return deps

    result: list[dict] = []
    for dep in deps:
        d = dict(dep)
        key = d.get("name", "").lower()
        if key in vuln_map:
            d["severity"] = "vulnerable"
            d["advisory_id"] = vuln_map[key]
        result.append(d)
    return result


def check_ruby_deps(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Orchestrate outdated + vuln checks for bundler deps in a repo.

    1. Filters deps to bundler-managed entries.
    2. Runs check_ruby_outdated on bundler deps.
    3. Runs check_ruby_vulns on bundler deps.
    4. Stamps required health fields on all bundler deps.
    5. Returns merged list (bundler enriched + non-bundler unchanged).
    """
    if not deps:
        return []

    ruby_deps = [d for d in deps if d.get("manager") == "bundler"]
    other_deps = [d for d in deps if d.get("manager") != "bundler"]

    if not ruby_deps:
        return other_deps

    ruby_deps = check_ruby_outdated(repo_path, ruby_deps)
    ruby_deps = check_ruby_vulns(repo_path, ruby_deps)

    now = datetime.now(timezone.utc).isoformat()
    enriched: list[dict] = []
    for dep in ruby_deps:
        d = dict(dep)
        ver = d.get("version")
        d.setdefault("current_version", ver)
        d.setdefault("wanted_version", ver)
        d.setdefault("latest_version", None)
        d.setdefault("severity", "ok")
        d.setdefault("advisory_id", None)
        d.setdefault("checked_at", now)
        enriched.append(d)

    return enriched + other_deps


# ── PHP dependency health (Packet 15) ─────────────────────────────────────────


def check_php_outdated(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Run composer outdated --format=json and enrich composer deps with version/severity fields.

    If composer is not available (TOOLS["composer"] is None), returns deps unchanged.
    Skips deps with latest-status == "up-to-date".
    On any subprocess or parse failure, returns deps unchanged (fail-open).
    """
    composer = TOOLS.get("composer")
    if not composer:
        return deps

    try:
        proc = subprocess.run(
            [composer, "outdated", "--format=json"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=120,
        )
        raw = json.loads(proc.stdout)
    except Exception as exc:
        logger.warning("composer outdated failed for %s: %s", repo_path, exc)
        return deps

    # Build lookup: {name: {"version": current, "latest": latest}}
    outdated_map: dict[str, dict] = {}
    try:
        for entry in raw.get("installed", []):
            status = entry.get("latest-status", "up-to-date")
            if status == "up-to-date":
                continue
            name = entry.get("name", "")
            if name:
                outdated_map[name] = {
                    "version": entry.get("version", ""),
                    "latest": entry.get("latest", ""),
                }
    except Exception as exc:
        logger.warning("composer outdated output parse error for %s: %s", repo_path, exc)
        return deps

    result: list[dict] = []
    for dep in deps:
        d = dict(dep)
        name = d.get("name", "")
        if name in outdated_map:
            info = outdated_map[name]
            current = info["version"]
            latest = info["latest"]
            d["current_version"] = current
            d["wanted_version"] = current  # composer has no "wanted" concept
            d["latest_version"] = latest
            if current and latest:
                d["severity"] = classify_severity(current, latest)
            else:
                d["severity"] = "outdated"
        result.append(d)
    return result


def check_php_vulns(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Run composer audit --format=json and merge vulnerability info into composer dep dicts.

    If composer is not available (TOOLS["composer"] is None), returns deps unchanged.
    Audit is built-in since Composer 2.4 — same binary, different subcommand.
    Vulnerability severity overrides any prior severity.
    Sets dep["severity"] = "vulnerable" and dep["advisory_id"] = advisory ID.
    """
    composer = TOOLS.get("composer")
    if not composer:
        return deps

    try:
        proc = subprocess.run(
            [composer, "audit", "--format=json"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=120,
        )
        raw = json.loads(proc.stdout)
    except Exception as exc:
        logger.warning("composer audit failed for %s: %s", repo_path, exc)
        return deps

    # Build lookup: {package_name: advisory_id}
    # composer audit JSON: {"advisories": {"pkg/name": [{"advisoryId": "...", ...}]}}
    vuln_map: dict[str, str] = {}
    try:
        for pkg_name, advisories in raw.get("advisories", {}).items():
            if advisories:
                advisory_id = advisories[0].get("advisoryId") or advisories[0].get("cve", "")
                if advisory_id:
                    vuln_map[pkg_name.lower()] = advisory_id
    except Exception as exc:
        logger.warning("composer audit output parse error for %s: %s", repo_path, exc)
        return deps

    result: list[dict] = []
    for dep in deps:
        d = dict(dep)
        key = d.get("name", "").lower()
        if key in vuln_map:
            d["severity"] = "vulnerable"
            d["advisory_id"] = vuln_map[key]
        result.append(d)
    return result


def check_php_deps(repo_path: Path, deps: list[dict]) -> list[dict]:
    """Orchestrate outdated + vuln checks for composer deps in a repo.

    1. Filters deps to composer-managed entries.
    2. Runs check_php_outdated on composer deps.
    3. Runs check_php_vulns on composer deps.
    4. Stamps required health fields on all composer deps.
    5. Returns merged list (composer enriched + non-composer unchanged).
    """
    if not deps:
        return []

    php_deps = [d for d in deps if d.get("manager") == "composer"]
    other_deps = [d for d in deps if d.get("manager") != "composer"]

    if not php_deps:
        return other_deps

    php_deps = check_php_outdated(repo_path, php_deps)
    php_deps = check_php_vulns(repo_path, php_deps)

    now = datetime.now(timezone.utc).isoformat()
    enriched: list[dict] = []
    for dep in php_deps:
        d = dict(dep)
        ver = d.get("version")
        d.setdefault("current_version", ver)
        d.setdefault("wanted_version", ver)
        d.setdefault("latest_version", None)
        d.setdefault("severity", "ok")
        d.setdefault("advisory_id", None)
        d.setdefault("checked_at", now)
        enriched.append(d)

    return enriched + other_deps


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
        help="Register and scan a directory on startup",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip missing-tools confirmation prompt (for scripted launches)",
    )
    return parser.parse_args(argv)


# ── HTML Shell & Design System (packet 04) ────────────────────────────────────
# Full CSS custom properties, React shell, hash routing, nav tabs, ErrorBoundary.
# Content areas are placeholders filled by later packets (05, 10, etc.).

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Git Fleet</title>
  <!-- Google Fonts (JetBrains Mono + Geist) -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Geist:wght@400;500;600&display=swap" rel="stylesheet">
  <!-- CDN dependencies (pinned versions per spec §5.1) -->
  <script crossorigin src="https://cdnjs.cloudflare.com/ajax/libs/react/18.2.0/umd/react.production.min.js"></script>
  <script crossorigin src="https://cdnjs.cloudflare.com/ajax/libs/react-dom/18.2.0/umd/react-dom.production.min.js"></script>
  <script crossorigin src="https://cdnjs.cloudflare.com/ajax/libs/babel-standalone/7.23.9/babel.min.js"></script>
  <script crossorigin src="https://cdnjs.cloudflare.com/ajax/libs/recharts/2.12.7/Recharts.min.js"></script>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg-primary);
      color: var(--text-primary);
      font-family: var(--font-body);
    }
    :root {
      /* Base */
      --bg-primary: #0f1117;
      --bg-secondary: #1a1d27;
      --bg-card: #1e2130;
      --bg-card-hover: #252838;
      --bg-input: #12141c;

      /* Borders */
      --border-default: #2a2d3a;
      --border-hover: #3a3d4a;

      /* Text */
      --text-primary: #e4e6ef;
      --text-secondary: #8b8fa3;
      --text-muted: #5a5e72;

      /* Accent */
      --accent-blue: #4c8dff;
      --accent-blue-dim: rgba(76,141,255,0.15);

      /* Status */
      --status-green: #34d399;
      --status-yellow: #fbbf24;
      --status-orange: #f97316;
      --status-red: #ef4444;
      --status-green-bg: rgba(52,211,153,0.12);
      --status-yellow-bg: rgba(251,191,36,0.12);
      --status-orange-bg: rgba(249,115,22,0.12);
      --status-red-bg: rgba(239,68,68,0.12);

      /* Freshness (card backgrounds + left border accents) */
      --fresh-this-week: var(--bg-card);
      --fresh-this-month: #1a1c28;
      --fresh-older: #16171f;
      --fresh-stale: #131420;

      /* Freshness left-border accents */
      --fresh-border-this-week: var(--accent-blue);
      --fresh-border-this-month: transparent;
      --fresh-border-older: transparent;
      --fresh-border-stale: var(--status-orange);

      /* Runtime colors (for badges/icons) */
      --runtime-python: #3776ab;
      --runtime-node: #339933;
      --runtime-go: #00add8;
      --runtime-rust: #dea584;
      --runtime-ruby: #cc342d;
      --runtime-php: #777bb4;
      --runtime-shell: #4eaa25;
      --runtime-docker: #2496ed;
      --runtime-html: #e34c26;

      /* Typography */
      --font-heading: 'JetBrains Mono', 'SF Mono', 'Fira Code', 'Consolas', monospace;
      --font-body: 'Geist', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
      --font-mono: 'JetBrains Mono', 'SF Mono', 'Fira Code', 'Consolas', monospace;

      /* Sizing */
      --radius-sm: 6px;
      --radius-md: 10px;
      --radius-lg: 14px;

      /* Transitions */
      --transition-fast: 100ms ease-out;
      --transition-normal: 150ms ease-out;
      --transition-slow: 200ms ease-out;
    }
    @keyframes toastSlideIn {
      from { transform: translateX(100%); opacity: 0; }
      to   { transform: translateX(0);   opacity: 1; }
    }
    @keyframes toastSlideOut {
      from { transform: translateX(0);   opacity: 1; }
      to   { transform: translateX(100%); opacity: 0; }
    }
    /* ── Global table styles (used by sub-tabs in packets 11, 17) ─────────── */
    .table-container { width: 100%; border-radius: var(--radius-md); overflow: hidden; }
    .table-header {
      background: var(--bg-secondary);
      display: grid;
      padding: 10px 16px;
      border-bottom: 1px solid var(--border-default);
      font-family: var(--font-body);
      font-size: 12px;
      font-weight: 600;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    .table-row {
      display: grid;
      padding: 12px 16px;
      border-bottom: 1px solid var(--border-default);
      font-family: var(--font-body);
      font-size: 14px;
      color: var(--text-primary);
      transition: background var(--transition-fast);
    }
    .table-row:last-child { border-bottom: none; }
    .table-row:nth-child(even) { background: rgba(255,255,255,0.02); }
    .table-row:hover { background: var(--bg-card-hover); }
    .table-empty {
      padding: 40px 16px;
      text-align: center;
      font-family: var(--font-body);
      font-size: 14px;
      color: var(--text-muted);
    }
    /* ── Detail view styles ─────────────────────────────────────────────────── */
    .detail-view { padding: 0; }
    .detail-header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      margin-bottom: 24px;
    }
    .detail-back-btn {
      display: flex;
      align-items: center;
      gap: 4px;
      background: none;
      border: none;
      cursor: pointer;
      font-family: var(--font-body);
      font-size: 13px;
      color: var(--text-secondary);
      padding: 4px 0;
      margin-bottom: 8px;
      transition: color var(--transition-fast);
    }
    .detail-back-btn:hover { color: var(--text-primary); }
    .detail-back-btn:focus-visible { outline: 2px solid var(--accent-blue); outline-offset: 2px; }
    .sub-tab-nav {
      display: flex;
      gap: 0;
      border-bottom: 1px solid var(--border-default);
      margin-bottom: 24px;
    }
    .sub-tab-btn {
      background: none;
      border: none;
      border-bottom: 2px solid transparent;
      margin-bottom: -1px;
      cursor: pointer;
      font-family: var(--font-heading);
      font-size: 13px;
      font-weight: 500;
      color: var(--text-secondary);
      padding: 8px 16px;
      transition: color var(--transition-fast), border-color var(--transition-fast);
    }
    .sub-tab-btn:hover { color: var(--text-primary); }
    .sub-tab-btn.active {
      color: var(--text-primary);
      border-bottom-color: var(--accent-blue);
    }
    .sub-tab-btn:focus-visible { outline: 2px solid var(--accent-blue); outline-offset: 2px; }
    .time-range-group {
      display: inline-flex;
      background: var(--bg-secondary);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-md);
      padding: 2px;
      gap: 2px;
      margin-bottom: 16px;
    }
    .time-range-btn {
      background: transparent;
      border: none;
      border-radius: var(--radius-sm);
      cursor: pointer;
      font-family: var(--font-heading);
      font-size: 12px;
      font-weight: 500;
      color: var(--text-secondary);
      padding: 4px 12px;
      transition: background var(--transition-fast), color var(--transition-fast);
    }
    .time-range-btn:hover { color: var(--text-primary); }
    .time-range-btn.active { background: var(--accent-blue); color: #fff; }
    .time-range-btn:focus-visible { outline: 2px solid var(--accent-blue); outline-offset: 2px; }
  </style>
</head>
<body>
  <div id="root"></div>
  <script type="text/babel">
    const { useState, useEffect, useRef, useLayoutEffect } = React;

    // ── ErrorBoundary ────────────────────────────────────────────────────────
    class ErrorBoundary extends React.Component {
      constructor(props) {
        super(props);
        this.state = { hasError: false, error: null };
      }
      static getDerivedStateFromError(error) {
        return { hasError: true, error };
      }
      componentDidCatch(error, info) {
        console.error('ErrorBoundary caught:', error, info);
      }
      render() {
        if (this.state.hasError) {
          return (
            <div style={{
              padding: '48px',
              textAlign: 'center',
              color: 'var(--status-red)',
              fontFamily: 'var(--font-mono)',
            }}>
              <p style={{ fontSize: '16px', marginBottom: '8px' }}>Something went wrong</p>
              <p style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
                {this.state.error && this.state.error.toString()}
              </p>
            </div>
          );
        }
        return this.props.children;
      }
    }

    // ── Hash routing hook ────────────────────────────────────────────────────
    function useHashRoute() {
      const [route, setRoute] = useState(window.location.hash || '#/fleet');
      useEffect(() => {
        const handler = () => setRoute(window.location.hash || '#/fleet');
        window.addEventListener('hashchange', handler);
        return () => window.removeEventListener('hashchange', handler);
      }, []);
      return route;
    }

    function parseRoute(hash) {
      if (!hash || hash === '#/' || hash === '#/fleet') return { tab: 'fleet', repoId: null, subTab: null };
      if (hash.startsWith('#/repo/')) {
        const rest = hash.slice(7);
        const slashIdx = rest.indexOf('/');
        if (slashIdx === -1) return { tab: 'repo', repoId: rest, subTab: null };
        return { tab: 'repo', repoId: rest.slice(0, slashIdx), subTab: rest.slice(slashIdx + 1) || null };
      }
      if (hash === '#/analytics') return { tab: 'analytics', repoId: null, subTab: null };
      if (hash === '#/deps') return { tab: 'deps', repoId: null, subTab: null };
      return { tab: 'fleet', repoId: null, subTab: null };
    }

    // ── Header ───────────────────────────────────────────────────────────────
    function Header({ onFullScan, scanActive }) {
      return (
        <header style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          height: '56px',
          background: 'var(--bg-secondary)',
          borderBottom: '1px solid var(--border-default)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 24px',
          zIndex: 100,
        }}>
          <span style={{
            fontFamily: 'var(--font-heading)',
            fontSize: '18px',
            fontWeight: 700,
            color: 'var(--text-primary)',
          }}>
            Git Fleet
          </span>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <button
              onClick={() => {}}
              style={{
                background: 'transparent',
                border: '1px solid var(--border-default)',
                color: 'var(--text-secondary)',
                fontFamily: 'var(--font-body)',
                fontSize: '13px',
                fontWeight: 500,
                padding: '8px 16px',
                borderRadius: 'var(--radius-sm)',
                cursor: 'pointer',
                transition: 'all var(--transition-fast)',
              }}
            >
              Scan Dir
            </button>
            <button
              onClick={onFullScan}
              disabled={scanActive}
              style={{
                background: scanActive ? 'var(--text-muted)' : 'var(--accent-blue)',
                border: 'none',
                color: '#fff',
                fontFamily: 'var(--font-body)',
                fontSize: '13px',
                fontWeight: 600,
                padding: '8px 16px',
                borderRadius: 'var(--radius-sm)',
                cursor: scanActive ? 'not-allowed' : 'pointer',
                transition: 'all var(--transition-fast)',
                opacity: scanActive ? 0.6 : 1,
              }}
            >
              Full Scan
            </button>
            <button
              onClick={() => {}}
              title="Settings"
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--text-muted)',
                cursor: 'pointer',
                padding: '8px',
                borderRadius: 'var(--radius-sm)',
                transition: 'all var(--transition-fast)',
                display: 'flex',
                alignItems: 'center',
              }}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="3"/>
                <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
              </svg>
            </button>
          </div>
        </header>
      );
    }

    // ── NavTabs ──────────────────────────────────────────────────────────────
    const TABS = [
      { id: 'fleet', label: 'Fleet Overview', hash: '#/fleet' },
      { id: 'analytics', label: 'Analytics', hash: '#/analytics' },
      { id: 'deps', label: 'Dependencies', hash: '#/deps' },
    ];

    function NavTabs({ activeTab }) {
      const tabRefs = useRef([]);
      const indicatorRef = useRef(null);

      useLayoutEffect(() => {
        const idx = TABS.findIndex(t => t.id === activeTab);
        const el = tabRefs.current[idx];
        const indicator = indicatorRef.current;
        if (el && indicator) {
          indicator.style.left = el.offsetLeft + 'px';
          indicator.style.width = el.offsetWidth + 'px';
        }
      }, [activeTab]);

      return (
        <nav style={{
          position: 'fixed',
          top: '56px',
          left: 0,
          right: 0,
          height: '44px',
          background: 'var(--bg-secondary)',
          borderBottom: '1px solid var(--border-default)',
          display: 'flex',
          alignItems: 'flex-end',
          padding: '0 24px',
          zIndex: 99,
        }}>
          <div style={{ position: 'relative', display: 'flex' }}>
            {TABS.map((tab, i) => (
              <a
                key={tab.id}
                href={tab.hash}
                ref={el => tabRefs.current[i] = el}
                style={{
                  display: 'block',
                  padding: '10px 16px',
                  fontFamily: 'var(--font-heading)',
                  fontSize: '14px',
                  fontWeight: 500,
                  color: activeTab === tab.id ? 'var(--accent-blue)' : 'var(--text-secondary)',
                  textDecoration: 'none',
                  transition: 'color var(--transition-fast)',
                  whiteSpace: 'nowrap',
                }}
              >
                {tab.label}
              </a>
            ))}
            <div
              ref={indicatorRef}
              style={{
                position: 'absolute',
                bottom: 0,
                height: '3px',
                background: 'var(--accent-blue)',
                borderRadius: '3px 3px 0 0',
                transition: 'left var(--transition-normal), width var(--transition-normal)',
                left: 0,
                width: 0,
              }}
            />
          </div>
        </nav>
      );
    }

    // ── ScanProgressBar ───────────────────────────────────────────────────────
    // Slim 3px bar below nav tabs, visible during and just after scan.
    function ScanProgressBar({ scanState }) {
      const { active, status, progress, total } = scanState;
      if (!active && status !== 'completed') return null;
      const pct = total > 0 ? Math.min((progress / total) * 100, 100) : (status === 'completed' ? 100 : 0);
      const fillColor = status === 'completed' ? 'var(--status-green)' : 'var(--accent-blue)';
      return (
        <div style={{
          position: 'fixed',
          top: '100px',   // header(56) + nav(44)
          left: 0,
          right: 0,
          height: '3px',
          background: 'var(--border-default)',
          zIndex: 98,
        }}>
          <div style={{
            height: '3px',
            width: pct + '%',
            background: fillColor,
            transition: 'width 300ms ease-out, background 300ms ease-out',
          }} />
        </div>
      );
    }

    // ── ScanToast ─────────────────────────────────────────────────────────────
    // Fixed bottom-right notification showing scan progress.
    function ScanToast({ scanState }) {
      const { active, status, progress, total, currentRepo } = scanState;
      const [visible, setVisible] = React.useState(false);
      const [slideOut, setSlideOut] = React.useState(false);

      React.useEffect(() => {
        if (active || status === 'completed') {
          setVisible(true);
          setSlideOut(false);
        }
        if (status === 'completed') {
          const t = setTimeout(() => setSlideOut(true), 2000);
          return () => clearTimeout(t);
        }
      }, [active, status]);

      if (!visible) return null;

      const pct = total > 0 ? Math.min((progress / total) * 100, 100) : (status === 'completed' ? 100 : 0);
      const fillColor = status === 'completed' ? 'var(--status-green)' : 'var(--accent-blue)';
      const heading = status === 'completed' ? 'Scan complete' : 'Scanning...';

      return (
        <div style={{
          position: 'fixed',
          bottom: '24px',
          right: '24px',
          width: '320px',
          background: 'var(--bg-card)',
          border: '1px solid var(--border-default)',
          borderRadius: 'var(--radius-md)',
          boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
          padding: '16px',
          zIndex: 200,
          animation: slideOut
            ? 'toastSlideOut var(--transition-slow) forwards'
            : 'toastSlideIn var(--transition-slow) forwards',
        }}>
          <div style={{
            fontFamily: 'var(--font-heading)',
            fontSize: '13px',
            fontWeight: 600,
            color: 'var(--text-primary)',
            marginBottom: '6px',
          }}>
            {heading}
          </div>
          {currentRepo && (
            <div style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '12px',
              color: 'var(--text-secondary)',
              marginBottom: '8px',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}>
              {currentRepo}
            </div>
          )}
          <div style={{ marginBottom: '4px' }}>
            <div style={{
              height: '4px',
              background: 'var(--border-default)',
              borderRadius: '2px',
              overflow: 'hidden',
            }}>
              <div style={{
                height: '4px',
                width: pct + '%',
                background: fillColor,
                transition: 'width 300ms ease-out, background 300ms ease-out',
              }} />
            </div>
          </div>
          <div style={{
            fontFamily: 'var(--font-body)',
            fontSize: '12px',
            color: 'var(--text-muted)',
            textAlign: 'right',
          }}>
            {progress} / {total || '?'}
          </div>
        </div>
      );
    }

    // ── Fleet Overview UI ─────────────────────────────────────────────────────

    // Runtime badge label mapping (§5.4 Project Card)
    const RUNTIME_LABELS = {
      python: 'PY', node: 'JS', go: 'GO', rust: 'RS', ruby: 'RB',
      php: 'PHP', shell: 'SH', docker: 'DK', html: 'HTML', mixed: 'MIX', unknown: '??'
    };

    // Relative time formatter — converts ISO 8601 date to "Xm/h/d/mo/y ago" or "never"
    function timeAgo(isoDate) {
      if (!isoDate) return 'never';
      const diffMs = Date.now() - new Date(isoDate).getTime();
      if (isNaN(diffMs) || diffMs < 0) return 'just now';
      const mins = Math.floor(diffMs / 60000);
      if (mins < 60) return mins <= 1 ? 'just now' : `${mins}m ago`;
      const hrs = Math.floor(mins / 60);
      if (hrs < 24) return `${hrs}h ago`;
      const days = Math.floor(hrs / 24);
      if (days < 30) return `${days}d ago`;
      const mos = Math.floor(days / 30);
      if (mos < 12) return `${mos}mo ago`;
      return `${Math.floor(mos / 12)}y ago`;
    }

    // Freshness classification — returns CSS bg var and optional border-left style
    function freshnessStyle(isoDate) {
      if (!isoDate) {
        return {
          background: 'var(--fresh-stale)',
          borderLeft: '3px solid var(--fresh-border-stale)',
        };
      }
      const days = (Date.now() - new Date(isoDate).getTime()) / 86400000;
      if (days <= 7) {
        return {
          background: 'var(--fresh-this-week)',
          borderLeft: '3px solid var(--fresh-border-this-week)',
        };
      }
      if (days <= 30) return { background: 'var(--fresh-this-month)' };
      if (days <= 90) return { background: 'var(--fresh-older)' };
      return {
        background: 'var(--fresh-stale)',
        borderLeft: '3px solid var(--fresh-border-stale)',
      };
    }

    // RuntimeBadge — colored abbreviation square
    function RuntimeBadge({ runtime }) {
      const type = (runtime || 'unknown').toLowerCase();
      const label = RUNTIME_LABELS[type] || '??';
      const color = `var(--runtime-${type}, var(--text-muted))`;
      return (
        <span style={{
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          width: '24px', height: '24px', flexShrink: 0,
          borderRadius: '4px',
          background: `color-mix(in srgb, ${color} 20%, transparent)`,
          color: color,
          fontFamily: 'var(--font-heading)',
          fontSize: '11px', fontWeight: 700,
        }}>
          {label}
        </span>
      );
    }

    // StatusPills — Clean or mod/new/staged pills
    function StatusPills({ repo }) {
      const { has_uncommitted, modified_count, untracked_count, staged_count } = repo;
      if (!has_uncommitted) {
        return (
          <span style={{
            fontSize: '11px', fontFamily: 'var(--font-body)', fontWeight: 500,
            padding: '2px 8px', borderRadius: '4px',
            color: 'var(--status-green)', background: 'var(--status-green-bg)',
          }}>Clean</span>
        );
      }
      const pills = [];
      if (modified_count > 0) pills.push({
        label: `${modified_count} mod`, color: 'var(--status-yellow)', bg: 'var(--status-yellow-bg)'
      });
      if (untracked_count > 0) pills.push({
        label: `${untracked_count} new`, color: 'var(--status-orange)', bg: 'var(--status-orange-bg)'
      });
      if (staged_count > 0) pills.push({
        label: `${staged_count} staged`, color: 'var(--accent-blue)', bg: 'var(--accent-blue-dim)'
      });
      return (
        <span style={{ display: 'inline-flex', gap: '4px', flexWrap: 'wrap' }}>
          {pills.map(p => (
            <span key={p.label} style={{
              fontSize: '11px', fontFamily: 'var(--font-body)', fontWeight: 500,
              padding: '2px 8px', borderRadius: '4px',
              color: p.color, background: p.bg,
            }}>{p.label}</span>
          ))}
        </span>
      );
    }

    // DepBadge — compact dep summary pill
    function DepBadge({ dep }) {
      if (!dep) return null;
      const { total, outdated, vulnerable } = dep;
      if (!total && total !== 0) return null;
      if (vulnerable > 0) {
        return (
          <span style={{
            fontSize: '11px', fontFamily: 'var(--font-mono)', fontWeight: 400,
            color: 'var(--status-red)',
          }}>{vulnerable} vuln</span>
        );
      }
      if (outdated > 0) {
        return (
          <span style={{
            fontSize: '11px', fontFamily: 'var(--font-mono)', fontWeight: 400,
            color: 'var(--status-yellow)',
          }}>{outdated} out</span>
        );
      }
      if (total > 0) {
        return (
          <span style={{
            fontSize: '11px', fontFamily: 'var(--font-mono)', fontWeight: 400,
            color: 'var(--text-muted)',
          }}>{total} deps</span>
        );
      }
      return null;
    }

    // SparklineOverlay — slides up from bottom on card hover
    function SparklineOverlay({ sparkline, visible }) {
      const { AreaChart, Area } = Recharts;
      const data = (sparkline || []).map((v, i) => ({ i, v }));
      return (
        <div style={{
          position: 'absolute', bottom: 0, left: 0, right: 0, height: '32px',
          overflow: 'hidden', pointerEvents: 'none',
          transform: visible ? 'translateY(0)' : 'translateY(100%)',
          transition: visible ? '150ms ease-out' : '100ms ease-in',
          background: 'linear-gradient(transparent, var(--bg-card) 30%)',
        }}>
          {data.length > 0 && (
            <AreaChart width={400} height={28} data={data}
              style={{ width: '100%' }}
              margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
              <Area type="monotone" dataKey="v"
                fill="var(--accent-blue-dim)" stroke="var(--accent-blue)"
                dot={false} isAnimationActive={false} />
            </AreaChart>
          )}
        </div>
      );
    }

    // ProjectCard — compact 3-row card
    function ProjectCard({ repo }) {
      const [hovered, setHovered] = useState(false);
      const [tooltipVisible, setTooltipVisible] = useState(false);

      const freshness = freshnessStyle(repo.last_commit_date);
      const cardStyle = {
        position: 'relative', overflow: 'hidden',
        borderRadius: 'var(--radius-md)',
        padding: '14px 16px',
        cursor: 'pointer',
        background: hovered ? 'var(--bg-card-hover)' : (freshness.background || 'var(--bg-card)'),
        border: freshness.borderLeft
          ? `1px solid ${hovered ? 'var(--border-hover)' : 'var(--border-default)'}`
          : `1px solid ${hovered ? 'var(--border-hover)' : 'var(--border-default)'}`,
        borderLeft: freshness.borderLeft || `1px solid ${hovered ? 'var(--border-hover)' : 'var(--border-default)'}`,
        transition: 'background var(--transition-fast), border-color var(--transition-fast)',
      };

      const branchColor = (repo.stale_branch_count || 0) > 0
        ? 'var(--status-orange)' : 'var(--text-muted)';

      return (
        <div
          style={cardStyle}
          onMouseEnter={() => setHovered(true)}
          onMouseLeave={() => setHovered(false)}
          onClick={() => { window.location.hash = '#/repo/' + repo.id; }}
        >
          {/* Row 1: RuntimeBadge + name (with tooltip) + time */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
            <RuntimeBadge runtime={repo.runtime} />
            <div style={{ position: 'relative', flex: 1, minWidth: 0 }}>
              <span
                style={{
                  display: 'block',
                  fontFamily: 'var(--font-heading)', fontSize: '16px', fontWeight: 600,
                  color: 'var(--text-primary)',
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  cursor: 'pointer',
                }}
                onMouseEnter={() => setTooltipVisible(true)}
                onMouseLeave={() => setTooltipVisible(false)}
              >
                {repo.name}
              </span>
              {tooltipVisible && (
                <div style={{
                  position: 'absolute', bottom: '100%', left: 0, zIndex: 10,
                  background: 'var(--bg-secondary)', border: '1px solid var(--border-default)',
                  borderRadius: 'var(--radius-sm)', padding: '6px 10px',
                  fontFamily: 'var(--font-mono)', fontSize: '12px', fontWeight: 400,
                  color: 'var(--text-secondary)', maxWidth: '500px',
                  whiteSpace: 'nowrap', pointerEvents: 'none',
                  marginBottom: '4px',
                }}>
                  {repo.path}
                </div>
              )}
            </div>
            <span style={{
              flexShrink: 0, fontSize: '13px',
              fontFamily: 'var(--font-body)', color: 'var(--text-secondary)',
            }}>
              {timeAgo(repo.last_commit_date)}
            </span>
          </div>

          {/* Row 2: Last commit message */}
          <div style={{
            fontSize: '13px', fontFamily: 'var(--font-body)', color: 'var(--text-secondary)',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            marginBottom: '8px', marginLeft: '32px',
          }}>
            {repo.last_commit_message || <span style={{ color: 'var(--text-muted)' }}>—</span>}
          </div>

          {/* Row 3: Status pills + branch + branch count + dep badge */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
            <StatusPills repo={repo} />
            <span style={{ flex: 1 }} />
            <span style={{
              fontSize: '13px', fontFamily: 'var(--font-mono)', fontWeight: 400,
              color: 'var(--text-secondary)',
            }}>
              {repo.current_branch}
            </span>
            <span style={{
              fontSize: '13px', fontFamily: 'var(--font-mono)', fontWeight: 400,
              color: branchColor,
            }}>
              {repo.branch_count || 0}br
            </span>
            <DepBadge dep={repo.dep_summary} />
          </div>

          <SparklineOverlay sparkline={repo.sparkline} visible={hovered} />
        </div>
      );
    }

    // KpiCard — single stat card
    function KpiCard({ value, label, color }) {
      return (
        <div style={{
          flex: '1 1 140px',
          background: 'var(--bg-card)',
          border: '1px solid var(--border-default)',
          borderRadius: 'var(--radius-md)',
          padding: '16px 20px',
        }}>
          <div style={{
            fontFamily: 'var(--font-heading)', fontSize: '28px', fontWeight: 700,
            color: color || 'var(--text-primary)',
            lineHeight: 1.1,
          }}>{value}</div>
          <div style={{
            fontFamily: 'var(--font-body)', fontSize: '12px', fontWeight: 500,
            color: 'var(--text-secondary)',
            textTransform: 'uppercase', letterSpacing: '0.5px',
            marginTop: '4px',
          }}>{label}</div>
        </div>
      );
    }

    // KpiRow — row of 6 KPI cards
    function KpiRow({ kpis }) {
      if (!kpis) return null;
      const dirtyColor = kpis.repos_with_changes > 0 ? 'var(--status-yellow)' : undefined;
      const staleColor = kpis.stale_branches > 0 ? 'var(--status-orange)' : undefined;
      const vulnColor = kpis.vulnerable_deps > 0 ? 'var(--status-red)' : undefined;
      const commitValue = `${kpis.commits_this_week ?? 0} / ${kpis.commits_this_month ?? 0}`;
      const locValue = kpis.net_lines_this_week > 0
        ? `+${(kpis.net_lines_this_week || 0).toLocaleString()}`
        : String(kpis.net_lines_this_week ?? 0);
      const vulnValue = `${kpis.vulnerable_deps ?? 0} / ${kpis.outdated_deps ?? 0}`;
      return (
        <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
          <KpiCard value={kpis.total_repos ?? 0} label="Repos" />
          <KpiCard value={kpis.repos_with_changes ?? 0} label="Dirty" color={dirtyColor} />
          <KpiCard value={commitValue} label="Commits" />
          <KpiCard value={locValue} label="Net LOC" />
          <KpiCard value={kpis.stale_branches ?? 0} label="Stale Br" color={staleColor} />
          <KpiCard value={vulnValue} label="Vuln/Out" color={vulnColor} />
        </div>
      );
    }

    // SortDropdown — custom (not native <select>) dropdown
    function SortDropdown({ value, onChange }) {
      const [open, setOpen] = useState(false);
      const ref = useRef(null);
      const options = [
        { value: 'last_active', label: 'Last active' },
        { value: 'name_az',    label: 'Name A-Z' },
        { value: 'most_changes', label: 'Most changes' },
        { value: 'most_stale', label: 'Most stale branches' },
      ];
      const current = options.find(o => o.value === value) || options[0];

      useEffect(() => {
        if (!open) return;
        const handler = (e) => {
          if (ref.current && !ref.current.contains(e.target)) setOpen(false);
        };
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
      }, [open]);

      return (
        <div ref={ref} style={{ position: 'relative', display: 'inline-block' }}>
          <button
            onClick={() => setOpen(o => !o)}
            style={{
              background: 'var(--bg-input)', border: '1px solid var(--border-default)',
              borderRadius: 'var(--radius-sm)', padding: '6px 12px',
              color: 'var(--text-primary)', fontFamily: 'var(--font-body)', fontSize: '13px',
              cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px',
              whiteSpace: 'nowrap',
            }}
          >
            {current.label}
            <svg width="10" height="6" viewBox="0 0 10 6" fill="none">
              <path d="M1 1l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
            </svg>
          </button>
          {open && (
            <div style={{
              position: 'absolute', top: '100%', left: 0, zIndex: 20, marginTop: '4px',
              background: 'var(--bg-input)', border: '1px solid var(--border-default)',
              borderRadius: 'var(--radius-sm)', minWidth: '180px', overflow: 'hidden',
            }}>
              {options.map(opt => (
                <div
                  key={opt.value}
                  onClick={() => { onChange(opt.value); setOpen(false); }}
                  style={{
                    padding: '8px 12px', cursor: 'pointer',
                    fontFamily: 'var(--font-body)', fontSize: '13px',
                    color: opt.value === value ? 'var(--accent-blue)' : 'var(--text-primary)',
                    background: opt.value === value ? 'var(--accent-blue-dim)' : 'transparent',
                  }}
                  onMouseEnter={e => { if (opt.value !== value) e.currentTarget.style.background = 'var(--bg-card-hover)'; }}
                  onMouseLeave={e => { if (opt.value !== value) e.currentTarget.style.background = 'transparent'; }}
                >
                  {opt.label}
                </div>
              ))}
            </div>
          )}
        </div>
      );
    }

    // GridControls — sort dropdown + filter input
    function GridControls({ sortBy, filterText, onSortChange, onFilterChange }) {
      return (
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '16px' }}>
          <SortDropdown value={sortBy} onChange={onSortChange} />
          <input
            type="text"
            placeholder="Filter projects..."
            value={filterText}
            onChange={e => onFilterChange(e.target.value)}
            style={{
              background: 'var(--bg-input)', border: '1px solid var(--border-default)',
              borderRadius: 'var(--radius-sm)', padding: '6px 12px',
              fontFamily: 'var(--font-body)', fontSize: '13px',
              color: 'var(--text-primary)', outline: 'none', width: '220px',
            }}
            onFocus={e => { e.target.style.borderColor = 'var(--accent-blue)'; }}
            onBlur={e => { e.target.style.borderColor = 'var(--border-default)'; }}
          />
        </div>
      );
    }

    // EmptyState — shown when no repos are registered
    function EmptyState() {
      return (
        <div style={{
          textAlign: 'center', padding: '64px 24px',
          color: 'var(--text-muted)',
        }}>
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none"
            style={{ color: 'var(--text-muted)', marginBottom: '16px' }}>
            <path d="M3 3h18v18H3zM9 9h6M9 12h6M9 15h4"
              stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
          </svg>
          <p style={{ fontFamily: 'var(--font-heading)', fontSize: '16px', marginBottom: '8px' }}>
            No repositories registered
          </p>
          <p style={{ fontFamily: 'var(--font-body)', fontSize: '14px' }}>
            Use "Scan Dir" in the header to add repositories.
          </p>
        </div>
      );
    }

    // sortRepos — pure sort function applied after filtering
    function sortRepos(repos, sortBy) {
      const sorted = [...repos];
      if (sortBy === 'name_az') {
        sorted.sort((a, b) => (a.name || '').toLowerCase().localeCompare((b.name || '').toLowerCase()));
      } else if (sortBy === 'most_changes') {
        sorted.sort((a, b) =>
          ((b.modified_count || 0) + (b.untracked_count || 0)) -
          ((a.modified_count || 0) + (a.untracked_count || 0))
        );
      } else if (sortBy === 'most_stale') {
        sorted.sort((a, b) => (b.stale_branch_count || 0) - (a.stale_branch_count || 0));
      } else {
        // last_active (default) — sort by last_commit_date desc, nulls last
        sorted.sort((a, b) => {
          if (!a.last_commit_date && !b.last_commit_date) return 0;
          if (!a.last_commit_date) return 1;
          if (!b.last_commit_date) return -1;
          return new Date(b.last_commit_date) - new Date(a.last_commit_date);
        });
      }
      return sorted;
    }

    // FleetOverview — main fleet tab component
    function FleetOverview({ refetchKey = 0 }) {
      const [data, setData] = useState(null);
      const [sortBy, setSortBy] = useState('last_active');
      const [filterText, setFilterText] = useState('');

      useEffect(() => {
        fetch('/api/fleet')
          .then(r => r.json())
          .then(d => setData(d))
          .catch(err => console.error('Fleet fetch error:', err));
      }, [refetchKey]);

      if (!data) {
        return (
          <div style={{ padding: '48px', textAlign: 'center', color: 'var(--text-muted)' }}>
            <p style={{ fontFamily: 'var(--font-heading)', fontSize: '14px' }}>Loading...</p>
          </div>
        );
      }

      const { repos = [], kpis } = data;

      // Filter then sort
      const filtered = repos.filter(r =>
        (r.name || '').toLowerCase().includes(filterText.toLowerCase())
      );
      const sorted = sortRepos(filtered, sortBy);

      return (
        <div>
          <KpiRow kpis={kpis} />
          <div style={{ marginTop: '24px' }}>
            <GridControls
              sortBy={sortBy}
              filterText={filterText}
              onSortChange={setSortBy}
              onFilterChange={setFilterText}
            />
            {repos.length === 0
              ? <EmptyState />
              : (
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))',
                  gap: '16px',
                }}>
                  {sorted.map(repo => <ProjectCard key={repo.id} repo={repo} />)}
                </div>
              )
            }
          </div>
        </div>
      );
    }

    // ── Project Detail Components ─────────────────────────────────────────────

    function DetailHeader({ repo }) {
      const scanAge = repo.working_state && repo.working_state.checked_at
        ? timeAgo(repo.working_state.checked_at)
        : (repo.last_full_scan_at ? timeAgo(repo.last_full_scan_at) : 'never');

      return (
        <div className="detail-header">
          <div>
            <button
              className="detail-back-btn"
              onClick={() => { window.location.hash = '#/fleet'; }}
              aria-label="Back to fleet"
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
                <path d="M9 2L4 7L9 12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
              Back
            </button>
            <h1 style={{ fontFamily: 'var(--font-heading)', fontSize: '24px', fontWeight: 700, color: 'var(--text-primary)', marginBottom: '4px' }}>
              {repo.name}
            </h1>
            <p style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-muted)', marginBottom: '6px' }}>
              {repo.path}
            </p>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontFamily: 'var(--font-body)', fontSize: '13px', color: 'var(--text-secondary)' }}>
              <RuntimeBadge runtime={repo.runtime} />
              <span>{repo.default_branch} branch</span>
              <span>·</span>
              <span>Last scanned {scanAge}</span>
            </div>
          </div>
          <button
            style={{
              background: 'none',
              border: '1px solid var(--border-default)',
              borderRadius: 'var(--radius-sm)',
              cursor: 'pointer',
              fontFamily: 'var(--font-body)',
              fontSize: '13px',
              color: 'var(--text-secondary)',
              padding: '6px 14px',
              transition: 'border-color var(--transition-fast), color var(--transition-fast)',
              marginTop: '24px',
            }}
            onClick={() => {}}
            title="Scan Now (not yet wired)"
          >
            Scan Now
          </button>
        </div>
      );
    }

    const SUB_TABS = [
      { id: 'activity', label: 'Activity' },
      { id: 'commits', label: 'Commits' },
      { id: 'branches', label: 'Branches' },
      { id: 'deps', label: 'Dependencies' },
    ];

    function SubTabNav({ active, onChange }) {
      return (
        <nav className="sub-tab-nav" role="tablist">
          {SUB_TABS.map(t => (
            <button
              key={t.id}
              role="tab"
              aria-selected={active === t.id}
              className={'sub-tab-btn' + (active === t.id ? ' active' : '')}
              onClick={() => onChange(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>
      );
    }

    const TIME_RANGES = [
      { label: '30d', days: 30 },
      { label: '90d', days: 90 },
      { label: '180d', days: 180 },
      { label: '1y',  days: 365 },
      { label: 'All', days: 9999 },
    ];

    function TimeRangeSelector({ selected, onChange }) {
      return (
        <div className="time-range-group" role="group" aria-label="Time range">
          {TIME_RANGES.map(r => (
            <button
              key={r.days}
              className={'time-range-btn' + (selected === r.days ? ' active' : '')}
              onClick={() => onChange(r.days)}
            >
              {r.label}
            </button>
          ))}
        </div>
      );
    }

    function fillDateGaps(data, days) {
      const map = {};
      data.forEach(d => { map[d.date] = d; });
      const result = [];
      const today = new Date();
      const limit = days >= 9999 ? (data.length > 0 ? null : 90) : days;
      if (limit === null) {
        // "All" mode: just return sorted data without gap filling beyond first date
        if (data.length === 0) return [];
        // Fill from earliest date to today
        const earliest = data[0].date;
        const start = new Date(earliest + 'T00:00:00');
        const end = new Date();
        for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
          const dateStr = d.toISOString().slice(0, 10);
          result.push(map[dateStr] || { date: dateStr, commits: 0, insertions: 0, deletions: 0, files_changed: 0 });
        }
        return result;
      }
      for (let i = limit - 1; i >= 0; i--) {
        const d = new Date(today);
        d.setDate(d.getDate() - i);
        const dateStr = d.toISOString().slice(0, 10);
        result.push(map[dateStr] || { date: dateStr, commits: 0, insertions: 0, deletions: 0, files_changed: 0 });
      }
      return result;
    }

    function ActivityChart({ data }) {
      const { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } = Recharts;

      if (!data || data.length === 0) {
        return (
          <div style={{ height: '300px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontFamily: 'var(--font-body)', fontSize: '14px' }}>
            No activity data for this period
          </div>
        );
      }

      // Negate deletions so they plot downward; compute net
      const chartData = data.map(d => ({
        date: d.date,
        insertions: d.insertions,
        deletions: -d.deletions,
        net: d.insertions - d.deletions,
        commits: d.commits,
      }));

      function CustomTooltip({ active, payload, label }) {
        if (!active || !payload || !payload.length) return null;
        const ins = payload.find(p => p.dataKey === 'insertions');
        const del = payload.find(p => p.dataKey === 'deletions');
        const net = payload.find(p => p.dataKey === 'net');
        const cmt = payload.find(p => p.dataKey === 'commits');
        const rawDel = del ? Math.abs(del.value) : 0;
        const netVal = net ? net.value : 0;
        return (
          <div style={{
            background: 'var(--bg-card)', border: '1px solid var(--border-default)',
            borderRadius: 'var(--radius-sm)', padding: '10px 14px',
            fontFamily: 'var(--font-body)', fontSize: '12px', color: 'var(--text-secondary)',
            lineHeight: '1.7',
          }}>
            <div style={{ color: 'var(--text-primary)', fontWeight: 600, marginBottom: '4px' }}>{label}</div>
            <div style={{ color: 'var(--status-green)' }}>+{ins ? ins.value : 0} insertions</div>
            <div style={{ color: 'var(--status-red)' }}>-{rawDel} deletions</div>
            <div style={{ color: 'var(--accent-blue)' }}>net {netVal >= 0 ? '+' : ''}{netVal}</div>
            <div>{cmt ? cmt.value : 0} commits</div>
          </div>
        );
      }

      // Show a tick every 7 data points
      const tickInterval = Math.max(Math.floor(chartData.length / 10), 6);

      return (
        <ResponsiveContainer width="100%" height={300}>
          <AreaChart data={chartData} stackOffset="sign" margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border-default)" vertical={false} />
            <XAxis
              dataKey="date"
              tick={{ fontFamily: 'var(--font-mono)', fontSize: 11, fill: 'var(--text-muted)' }}
              interval={tickInterval}
              tickLine={false}
              axisLine={{ stroke: 'var(--border-default)' }}
            />
            <YAxis
              tick={{ fontFamily: 'var(--font-mono)', fontSize: 11, fill: 'var(--text-muted)' }}
              tickLine={false}
              axisLine={false}
              tickFormatter={v => v < 0 ? String(-v) : String(v)}
            />
            <ReferenceLine y={0} stroke="var(--border-default)" strokeWidth={1} />
            <Tooltip content={<CustomTooltip />} />
            <Area
              type="monotone"
              dataKey="insertions"
              stackId="stack"
              fill="var(--status-green)"
              fillOpacity={0.2}
              stroke="var(--status-green)"
              strokeWidth={1.5}
              isAnimationActive={false}
            />
            <Area
              type="monotone"
              dataKey="deletions"
              stackId="stack"
              fill="var(--status-red)"
              fillOpacity={0.2}
              stroke="var(--status-red)"
              strokeWidth={1.5}
              isAnimationActive={false}
            />
            <Area
              type="monotone"
              dataKey="net"
              fill="none"
              stroke="var(--accent-blue)"
              strokeWidth={2}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      );
    }

    function ActivityTab({ repoId }) {
      const [selectedDays, setSelectedDays] = useState(90);
      const [historyData, setHistoryData] = useState(null);

      useEffect(() => {
        setHistoryData(null);
        fetch(`/api/repos/${repoId}/history?days=${selectedDays}`)
          .then(r => r.json())
          .then(d => {
            const filled = fillDateGaps(d.data || [], selectedDays);
            setHistoryData(filled);
          })
          .catch(() => setHistoryData([]));
      }, [repoId, selectedDays]);

      return (
        <div>
          <TimeRangeSelector selected={selectedDays} onChange={setSelectedDays} />
          {historyData === null
            ? <div style={{ height: '300px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontFamily: 'var(--font-body)', fontSize: '14px' }}>Loading…</div>
            : <ActivityChart data={historyData} />
          }
        </div>
      );
    }

    function CommitsTab({ repoId }) {
      const PER_PAGE = 25;
      const [commits, setCommits] = useState([]);
      const [page, setPage] = useState(1);
      const [total, setTotal] = useState(0);
      const [loading, setLoading] = useState(true);

      useEffect(() => {
        setLoading(true);
        fetch(`/api/repos/${repoId}/commits?page=${page}&per_page=${PER_PAGE}`)
          .then(r => r.json())
          .then(data => {
            setCommits(data.commits || []);
            setTotal(data.total || 0);
            setLoading(false);
          })
          .catch(() => setLoading(false));
      }, [repoId, page]);

      const totalPages = Math.max(1, Math.ceil(total / PER_PAGE));

      function fmtDate(isoStr) {
        if (!isoStr) return '—';
        return isoStr.slice(0, 10);
      }

      if (loading) {
        return <div className="table-empty">Loading…</div>;
      }

      return (
        <div>
          <div className="table-container">
            <div className="table-header" style={{ gridTemplateColumns: '120px 1fr 110px 70px' }}>
              <span>Date</span>
              <span>Message</span>
              <span>+/-</span>
              <span>Files</span>
            </div>
            {commits.length === 0 ? (
              <div className="table-empty">No commits found</div>
            ) : commits.map(c => (
              <div key={c.hash} className="table-row" style={{ gridTemplateColumns: '120px 1fr 110px 70px' }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '13px', color: 'var(--text-secondary)' }}>
                  {fmtDate(c.date)}
                </span>
                <span style={{ fontFamily: 'var(--font-body)', fontSize: '14px', color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {c.message && c.message.length > 80 ? c.message.slice(0, 80) + '…' : (c.message || '')}
                </span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '13px' }}>
                  <span style={{ color: 'var(--status-green)' }}>+{c.insertions}</span>
                  {' '}
                  <span style={{ color: 'var(--status-red)' }}>-{c.deletions}</span>
                </span>
                <span style={{ fontFamily: 'var(--font-body)', fontSize: '13px', color: 'var(--text-muted)' }}>
                  {c.files_changed}
                </span>
              </div>
            ))}
          </div>
          <div style={{ marginTop: '16px', display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '12px' }}>
            <button
              className="btn btn-secondary"
              disabled={page <= 1}
              onClick={() => setPage(p => p - 1)}
            >Prev</button>
            <span style={{ fontSize: '13px', fontFamily: 'var(--font-body)', color: 'var(--text-secondary)' }}>
              Page {page} of {totalPages}
            </span>
            <button
              className="btn btn-secondary"
              disabled={page >= totalPages}
              onClick={() => setPage(p => p + 1)}
            >Next</button>
          </div>
        </div>
      );
    }

    function BranchesTab({ repoId }) {
      const [branches, setBranches] = useState([]);
      const [loading, setLoading] = useState(true);

      useEffect(() => {
        setLoading(true);
        fetch(`/api/repos/${repoId}/branches`)
          .then(r => r.json())
          .then(data => {
            setBranches(data.branches || []);
            setLoading(false);
          })
          .catch(() => setLoading(false));
      }, [repoId]);

      function staleDays(dateStr) {
        if (!dateStr) return 0;
        const ms = Date.now() - new Date(dateStr).getTime();
        return Math.floor(ms / (1000 * 60 * 60 * 24));
      }

      function fmtDate(isoStr) {
        if (!isoStr) return '—';
        return isoStr.slice(0, 10);
      }

      if (loading) {
        return <div className="table-empty">Loading…</div>;
      }

      return (
        <div className="table-container">
          <div className="table-header" style={{ gridTemplateColumns: '1fr 140px 160px' }}>
            <span>Branch</span>
            <span>Last Commit</span>
            <span>Status</span>
          </div>
          {branches.length === 0 ? (
            <div className="table-empty">No branches found</div>
          ) : branches.map(b => (
            <div key={b.name} className="table-row" style={{ gridTemplateColumns: '1fr 140px 160px' }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '14px', color: 'var(--text-primary)' }}>
                {b.name}
              </span>
              <span style={{ fontSize: '13px', fontFamily: 'var(--font-body)', color: 'var(--text-secondary)' }}>
                {fmtDate(b.last_commit_date)}
              </span>
              <span>
                {b.is_default ? (
                  <span style={{ color: 'var(--accent-blue)', background: 'var(--accent-blue-dim)', fontSize: '11px', fontFamily: 'var(--font-body)', fontWeight: 500, padding: '2px 8px', borderRadius: '4px' }}>
                    default
                  </span>
                ) : b.is_stale ? (
                  <span style={{ color: 'var(--status-orange)', background: 'var(--status-orange-bg)', fontSize: '11px', fontFamily: 'var(--font-body)', fontWeight: 500, padding: '2px 8px', borderRadius: '4px' }}>
                    stale ({staleDays(b.last_commit_date)} days)
                  </span>
                ) : (
                  <span style={{ fontSize: '13px', fontFamily: 'var(--font-body)', color: 'var(--text-muted)' }}>
                    active
                  </span>
                )}
              </span>
            </div>
          ))}
        </div>
      );
    }

    function DepsTab({ repoId }) {
      const [managerGroups, setManagerGroups] = useState([]);
      const [loading, setLoading] = useState(true);
      const [scanning, setScanning] = useState(false);

      function fetchDeps() {
        setLoading(true);
        fetch(`/api/repos/${repoId}/deps`)
          .then(r => r.json())
          .then(data => {
            setManagerGroups(Array.isArray(data) ? data : []);
            setLoading(false);
          })
          .catch(() => setLoading(false));
      }

      useEffect(() => { fetchDeps(); }, [repoId]);

      function handleCheckNow() {
        setScanning(true);
        fetch(`/api/repos/${repoId}/scan/deps`, { method: 'POST' })
          .then(r => r.json())
          .then(data => {
            setManagerGroups(Array.isArray(data) ? data : []);
            setScanning(false);
          })
          .catch(() => setScanning(false));
      }

      function severityColor(severity) {
        switch (severity) {
          case 'ok':         return 'var(--status-green)';
          case 'outdated':   return 'var(--status-yellow)';
          case 'major':      return 'var(--status-orange)';
          case 'vulnerable': return 'var(--status-red)';
          default:           return 'var(--text-muted)';
        }
      }

      function severityText(pkg) {
        switch (pkg.severity) {
          case 'ok':         return 'up to date';
          case 'outdated':   return 'outdated';
          case 'major':      return 'major update';
          case 'vulnerable': return pkg.advisory_id || 'vulnerable';
          default:           return pkg.severity || '—';
        }
      }

      if (loading) {
        return <div className="table-empty">Loading…</div>;
      }

      if (managerGroups.length === 0) {
        return (
          <div className="table-container">
            <div className="table-empty">No dependencies detected</div>
          </div>
        );
      }

      return (
        <div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '12px' }}>
            <button
              className="btn btn-secondary"
              onClick={handleCheckNow}
              disabled={scanning}
            >
              {scanning ? 'Checking…' : 'Check Now'}
            </button>
          </div>
          {managerGroups.map(group => (
            <div key={group.manager} style={{ marginBottom: '24px' }}>
              <div style={{
                fontSize: '12px', fontFamily: 'var(--font-heading)', fontWeight: 600,
                color: 'var(--text-muted)', marginBottom: '8px',
                textTransform: 'uppercase', letterSpacing: '0.5px',
              }}>
                {group.manager}
              </div>
              <div className="table-container">
                <div className="table-header" style={{ gridTemplateColumns: '1fr 100px 100px 160px' }}>
                  <span>Package</span>
                  <span>Current</span>
                  <span>Latest</span>
                  <span>Status</span>
                </div>
                {group.packages.map(pkg => (
                  <div key={pkg.name} className="table-row"
                    style={{ gridTemplateColumns: '1fr 100px 100px 160px' }}>
                    <span style={{
                      fontFamily: 'var(--font-mono)', fontSize: '14px',
                      color: 'var(--text-primary)',
                    }}>
                      {pkg.name}
                    </span>
                    <span style={{
                      fontFamily: 'var(--font-mono)', fontSize: '13px',
                      color: 'var(--text-secondary)',
                    }}>
                      {pkg.current_version || '—'}
                    </span>
                    <span style={{
                      fontFamily: 'var(--font-mono)', fontSize: '13px',
                      color: 'var(--text-secondary)',
                      fontWeight: (pkg.current_version !== pkg.latest_version) ? 600 : 400,
                    }}>
                      {pkg.latest_version || '—'}
                    </span>
                    <span style={{
                      color: severityColor(pkg.severity), fontSize: '13px',
                      fontFamily: 'var(--font-body)',
                      fontWeight: pkg.severity === 'vulnerable' ? 600 : 400,
                    }}>
                      {severityText(pkg)}
                    </span>
                  </div>
                ))}
              </div>
              <div style={{
                fontSize: '13px', fontFamily: 'var(--font-body)',
                color: 'var(--text-muted)', marginTop: '6px',
              }}>
                Last checked: {timeAgo(group.checked_at)}
              </div>
            </div>
          ))}
        </div>
      );
    }

    function PlaceholderTab({ text }) {
      return (
        <div className="table-container">
          <div className="table-empty">{text} — coming in a later packet</div>
        </div>
      );
    }

    function ProjectDetail({ repoId, initialSubTab }) {
      const [repo, setRepo] = useState(null);
      const [activeSubTab, setActiveSubTab] = useState(initialSubTab || 'activity');

      useEffect(() => {
        setRepo(null);
        fetch(`/api/repos/${repoId}`)
          .then(r => r.json())
          .then(setRepo)
          .catch(() => {});
      }, [repoId]);

      function handleSubTabChange(tabId) {
        setActiveSubTab(tabId);
        window.location.hash = `#/repo/${repoId}/${tabId}`;
      }

      if (!repo) {
        return (
          <div style={{ padding: '48px', textAlign: 'center', color: 'var(--text-muted)', fontFamily: 'var(--font-body)', fontSize: '14px' }}>
            Loading…
          </div>
        );
      }

      return (
        <div className="detail-view">
          <DetailHeader repo={repo} />
          <SubTabNav active={activeSubTab} onChange={handleSubTabChange} />
          <div className="detail-content">
            {activeSubTab === 'activity'  && <ActivityTab repoId={repoId} />}
            {activeSubTab === 'commits'   && <CommitsTab repoId={repoId} />}
            {activeSubTab === 'branches'  && <BranchesTab repoId={repoId} />}
            {activeSubTab === 'deps'      && <DepsTab repoId={repoId} />}
          </div>
        </div>
      );
    }

    // ── ContentArea ──────────────────────────────────────────────────────────
    function ContentArea({ route, refetchKey = 0 }) {
      const { tab, repoId } = route;
      const [visible, setVisible] = useState(false);

      useEffect(() => {
        setVisible(false);
        const t = setTimeout(() => setVisible(true), 10);
        return () => clearTimeout(t);
      }, [tab, repoId]);

      const areaStyle = {
        opacity: visible ? 1 : 0,
        transform: visible ? 'translateY(0)' : 'translateY(8px)',
        transition: 'opacity var(--transition-fast), transform var(--transition-fast)',
        padding: '24px',
        maxWidth: '1400px',
        margin: '0 auto',
      };

      let content;
      if (tab === 'repo' && repoId) {
        content = <ProjectDetail key={repoId} repoId={repoId} initialSubTab={route.subTab} />;
      } else if (tab === 'analytics') {
        content = (
          <div style={{ padding: '48px', textAlign: 'center', color: 'var(--text-muted)' }}>
            <p style={{ fontFamily: 'var(--font-heading)', fontSize: '16px' }}>
              Analytics — coming soon
            </p>
          </div>
        );
      } else if (tab === 'deps') {
        content = (
          <div style={{ padding: '48px', textAlign: 'center', color: 'var(--text-muted)' }}>
            <p style={{ fontFamily: 'var(--font-heading)', fontSize: '16px' }}>
              Dependencies — coming soon
            </p>
          </div>
        );
      } else {
        content = <FleetOverview refetchKey={refetchKey} />;
      }

      return <div style={areaStyle}>{content}</div>;
    }

    // ── App ──────────────────────────────────────────────────────────────────
    function App() {
      const hash = useHashRoute();
      const route = parseRoute(hash);
      const navTab = route.tab === 'repo' ? 'fleet' : route.tab;

      const [scanState, setScanState] = useState({
        active: false,
        scanId: null,
        progress: 0,
        total: 0,
        currentRepo: '',
        status: 'idle',
      });
      const [refetchKey, setRefetchKey] = useState(0);

      async function handleFullScan() {
        if (scanState.active) return;
        let res;
        try {
          res = await fetch('/api/fleet/scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type: 'full' }),
          });
        } catch (err) {
          console.error('Full scan POST failed:', err);
          return;
        }
        if (res.status === 409) return; // already scanning
        const { scan_id } = await res.json();
        setScanState({ active: true, scanId: scan_id, progress: 0, total: 0, currentRepo: '', status: 'scanning' });

        const es = new EventSource(`/api/fleet/scan/${scan_id}/progress`);
        es.onmessage = (e) => {
          const data = JSON.parse(e.data);
          setScanState(prev => ({
            ...prev,
            progress: data.progress ?? prev.progress,
            total: data.total ?? prev.total,
            currentRepo: data.repo ?? prev.currentRepo,
            status: data.status ?? prev.status,
            active: data.status !== 'completed' && data.status !== 'failed',
          }));
          if (data.status === 'completed' || data.status === 'failed') {
            es.close();
            setRefetchKey(k => k + 1);
            setTimeout(() => setScanState({
              active: false, scanId: null, progress: 0, total: 0, currentRepo: '', status: 'idle',
            }), 2000);
          }
        };
        es.onerror = () => {
          es.close();
          setScanState(prev => ({ ...prev, active: false, status: 'failed' }));
        };
      }

      return (
        <div>
          <Header onFullScan={handleFullScan} scanActive={scanState.active} />
          <NavTabs activeTab={navTab} />
          <ScanProgressBar scanState={scanState} />
          <ScanToast scanState={scanState} />
          <main style={{ paddingTop: '100px' }}>
            <ContentArea route={route} refetchKey={refetchKey} />
          </main>
        </div>
      );
    }

    // ── Mount ────────────────────────────────────────────────────────────────
    ReactDOM.createRoot(document.getElementById('root')).render(
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    );
  </script>
</body>
</html>
"""


# ── FastAPI application ───────────────────────────────────────────────────────

app = FastAPI(title="Git Fleet")


@app.get("/", response_class=HTMLResponse)
async def get_ui():
    """Serve the SPA shell."""
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


# ── Fleet Scan endpoints (packet 08) ──────────────────────────────────────────

class _ScanRequest(BaseModel):
    type: Literal["full", "deps"]


@app.post("/api/fleet/scan")
async def post_fleet_scan(body: _ScanRequest, db=Depends(get_db)):
    """Trigger a fleet scan. Returns immediately with a scan_id; progress via SSE.

    Rejects with 409 if a scan is already running (checked via module-level
    variable for fast path, and DB query for correctness after server restart).
    """
    global _active_scan_id, _scan_task

    # Fast-path in-memory check
    if _active_scan_id is not None:
        raise HTTPException(status_code=409, detail="A scan is already running")

    # Belt-and-suspenders DB check (correct after server restart)
    cursor = await db.execute(
        "SELECT id FROM scan_log WHERE status = 'running' LIMIT 1"
    )
    row = await cursor.fetchone()
    if row is not None:
        raise HTTPException(status_code=409, detail="A scan is already running")

    # Create scan_log entry
    now = datetime.now(timezone.utc).isoformat()
    cursor = await db.execute(
        "INSERT INTO scan_log (scan_type, started_at, status) VALUES (?, ?, 'running')",
        (body.type, now),
    )
    await db.commit()
    scan_id = cursor.lastrowid

    # Mark active and launch background task
    _active_scan_id = scan_id
    _scan_task = asyncio.create_task(run_fleet_scan(scan_id, body.type))

    return {"scan_id": scan_id}


@app.get("/api/fleet/scan/{scan_id}/progress")
async def scan_progress_sse(scan_id: int):
    """SSE endpoint for real-time scan progress.

    Streams data events until the scan completes or fails.
    Event format: data: {<json>}\\n\\n
    """
    q: asyncio.Queue = asyncio.Queue()
    _scan_queues[scan_id] = q

    async def event_generator():
        try:
            while True:
                event = await q.get()
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("status") in ("completed", "failed"):
                    break
        finally:
            _scan_queues.pop(scan_id, None)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ── Project Detail API ────────────────────────────────────────────────────────

@app.get("/api/repos/{repo_id}")
async def get_repo_detail(repo_id: str, db=Depends(get_db)):
    """Return full detail for one repo: repositories row + working_state."""
    cursor = await db.execute(
        "SELECT id, name, path, runtime, default_branch, last_full_scan_at "
        "FROM repositories WHERE id = ?",
        (repo_id,),
    )
    repo = await cursor.fetchone()
    if not repo:
        raise HTTPException(status_code=404, detail="Repo not found")

    ws_cursor = await db.execute(
        "SELECT repo_id, has_uncommitted, modified_count, untracked_count, "
        "staged_count, current_branch, last_commit_hash, last_commit_message, "
        "last_commit_date, checked_at "
        "FROM working_state WHERE repo_id = ?",
        (repo_id,),
    )
    ws_row = await ws_cursor.fetchone()
    ws = None
    if ws_row:
        ws = {
            "repo_id": ws_row[0],
            "has_uncommitted": bool(ws_row[1]),
            "modified_count": ws_row[2],
            "untracked_count": ws_row[3],
            "staged_count": ws_row[4],
            "current_branch": ws_row[5],
            "last_commit_hash": ws_row[6],
            "last_commit_message": ws_row[7],
            "last_commit_date": ws_row[8],
            "checked_at": ws_row[9],
        }

    return {
        "id": repo[0],
        "name": repo[1],
        "path": repo[2],
        "runtime": repo[3],
        "default_branch": repo[4],
        "last_full_scan_at": repo[5],
        "working_state": ws,
    }


@app.get("/api/repos/{repo_id}/history")
async def get_repo_history(repo_id: str, days: int = 90, db=Depends(get_db)):
    """Return daily_stats rows for the repo within the requested time window.

    Only dates with activity are included. Frontend fills date gaps with zeros.
    """
    import datetime as _dt_mod

    cursor = await db.execute(
        "SELECT id FROM repositories WHERE id = ?", (repo_id,)
    )
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Repo not found")

    cutoff = (
        _dt_mod.date.today() - _dt_mod.timedelta(days=days)
    ).isoformat()

    cursor = await db.execute(
        "SELECT date, commits, insertions, deletions, files_changed "
        "FROM daily_stats WHERE repo_id = ? AND date >= ? ORDER BY date",
        (repo_id, cutoff),
    )
    rows = await cursor.fetchall()

    return {
        "repo_id": repo_id,
        "days": days,
        "data": [
            {
                "date": r[0],
                "commits": r[1],
                "insertions": r[2],
                "deletions": r[3],
                "files_changed": r[4],
            }
            for r in rows
        ],
    }


@app.get("/api/repos/{repo_id}/commits")
async def get_repo_commits(
    repo_id: str, page: int = 1, per_page: int = 25, db=Depends(get_db)
):
    """Return paginated commit history for one repo via live git log query."""
    page = max(1, page)
    per_page = max(1, min(100, per_page))

    cursor = await db.execute(
        "SELECT path FROM repositories WHERE id = ?", (repo_id,)
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Repo not found")

    repo_path = row[0]
    if not Path(repo_path).is_dir():
        raise HTTPException(status_code=404, detail="Repo path not found on disk")

    # Total commit count via rev-list --count --all
    stdout, _, rc = await run_git(repo_path, "rev-list", "--count", "--all")
    total = int(stdout.strip()) if rc == 0 and stdout.strip().isdigit() else 0

    if total == 0:
        return {"commits": [], "page": page, "per_page": per_page, "total": 0}

    skip = (page - 1) * per_page
    stdout, _, rc = await run_git(
        repo_path,
        "log", "--all",
        "--format=%H%x00%aI%x00%an%x00%s",
        "--shortstat",
        f"--skip={skip}",
        f"--max-count={per_page}",
    )

    parsed = parse_git_log(stdout) if rc == 0 else []
    commits = [
        {
            "hash": c["hash"],
            "date": c["date"],
            "author": c["author"],
            "message": c["subject"],
            "insertions": c["insertions"],
            "deletions": c["deletions"],
            "files_changed": c["files_changed"],
        }
        for c in parsed
    ]

    return {"commits": commits, "page": page, "per_page": per_page, "total": total}


@app.get("/api/repos/{repo_id}/branches")
async def get_repo_branches(repo_id: str, db=Depends(get_db)):
    """Return branches for one repo from the branches table, sorted default-first then by date."""
    cursor = await db.execute(
        "SELECT id FROM repositories WHERE id = ?", (repo_id,)
    )
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Repo not found")

    cursor = await db.execute(
        "SELECT name, last_commit_date, is_default, is_stale "
        "FROM branches "
        "WHERE repo_id = ? "
        "ORDER BY is_default DESC, last_commit_date DESC",
        (repo_id,),
    )
    rows = await cursor.fetchall()

    return {
        "branches": [
            {
                "name": r[0],
                "last_commit_date": r[1],
                "is_default": bool(r[2]),
                "is_stale": bool(r[3]),
            }
            for r in rows
        ]
    }


# ── Deps API ──────────────────────────────────────────────────────────────────

async def _fetch_repo_deps(repo_id: str, db):
    """Shared helper: query and group dependency rows for one repo."""
    cursor = await db.execute(
        """
        SELECT manager, name, current_version, wanted_version, latest_version,
               severity, advisory_id, checked_at
        FROM dependencies
        WHERE repo_id = ?
        ORDER BY manager,
          CASE severity
            WHEN 'vulnerable' THEN 0
            WHEN 'major' THEN 1
            WHEN 'outdated' THEN 2
            ELSE 3
          END,
          name
        """,
        (repo_id,),
    )
    rows = await cursor.fetchall()

    result = []
    manager_index = {}
    for row in rows:
        mgr, name, cur_ver, wanted_ver, latest_ver, severity, advisory_id, checked_at = row
        if mgr not in manager_index:
            manager_index[mgr] = len(result)
            result.append({"manager": mgr, "packages": [], "checked_at": checked_at})
        else:
            # Track MAX checked_at within the manager group
            existing = result[manager_index[mgr]]
            if checked_at and (
                not existing["checked_at"] or checked_at > existing["checked_at"]
            ):
                existing["checked_at"] = checked_at
        result[manager_index[mgr]]["packages"].append(
            {
                "name": name,
                "current_version": cur_ver,
                "wanted_version": wanted_ver,
                "latest_version": latest_ver,
                "severity": severity,
                "advisory_id": advisory_id,
            }
        )
    return result


@app.get("/api/repos/{repo_id}/deps")
async def get_repo_deps(repo_id: str, db=Depends(get_db)):
    """Return dependency groups for one repo, sorted by severity."""
    cursor = await db.execute("SELECT id FROM repositories WHERE id = ?", (repo_id,))
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Repo not found")
    return await _fetch_repo_deps(repo_id, db)


@app.post("/api/repos/{repo_id}/scan/deps")
async def scan_repo_deps(repo_id: str, db=Depends(get_db)):
    """Run a dep scan for one repo synchronously and return the updated deps list."""
    cursor = await db.execute(
        "SELECT id, path FROM repositories WHERE id = ?", (repo_id,)
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Repo not found")
    repo_id_val, repo_path = row
    await run_dep_scan_for_repo(db, repo_id_val, repo_path)
    return await _fetch_repo_deps(repo_id_val, db)


# ── Fleet API ─────────────────────────────────────────────────────────────────

@app.get("/api/fleet")
async def get_fleet(db=Depends(get_db)):
    """Quick-scan all registered repos and return the fleet overview.

    Runs up to 8 scans in parallel (asyncio.Semaphore(8)), upserts working_state,
    and returns per-repo data with branch counts from the branches table and
    KPIs aggregated from daily_stats.
    """
    results = await scan_fleet_quick(db)

    # Bulk-compute sparklines once for all repos (packet 09)
    sparklines = await compute_sparklines(db)

    # Augment with branch counts from branches table (packet 08) and placeholders
    for repo in results:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM branches WHERE repo_id = ?", (repo["id"],)
        )
        (branch_count,) = await cursor.fetchone()
        cursor = await db.execute(
            "SELECT COUNT(*) FROM branches WHERE repo_id = ? AND is_stale = 1",
            (repo["id"],),
        )
        (stale_count,) = await cursor.fetchone()
        repo["branch_count"] = branch_count
        repo["stale_branch_count"] = stale_count
        # Compute dep_summary from dependencies table
        cursor = await db.execute(
            "SELECT COUNT(*), "
            "SUM(CASE WHEN severity IN ('outdated', 'major') THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN severity = 'vulnerable' THEN 1 ELSE 0 END) "
            "FROM dependencies WHERE repo_id = ?",
            (repo["id"],),
        )
        total_deps, outdated_count, vuln_count = await cursor.fetchone()
        if total_deps and total_deps > 0:
            repo["dep_summary"] = {
                "total": total_deps,
                "outdated": (outdated_count or 0),
                "vulnerable": (vuln_count or 0),
            }
        else:
            repo["dep_summary"] = None
        repo["sparkline"] = sparklines.get(repo["id"], [0] * 13)

    # Compute KPIs from daily_stats (packets 06-08) and branches table (packet 07)
    now_utc = datetime.now(timezone.utc)
    week_ago = (now_utc - timedelta(days=7)).strftime("%Y-%m-%d")
    month_ago = (now_utc - timedelta(days=30)).strftime("%Y-%m-%d")

    cursor = await db.execute(
        "SELECT COALESCE(SUM(commits), 0) FROM daily_stats WHERE date >= ?", (week_ago,)
    )
    commits_this_week = (await cursor.fetchone())[0]

    cursor = await db.execute(
        "SELECT COALESCE(SUM(commits), 0) FROM daily_stats WHERE date >= ?", (month_ago,)
    )
    commits_this_month = (await cursor.fetchone())[0]

    cursor = await db.execute(
        "SELECT COALESCE(SUM(insertions), 0) - COALESCE(SUM(deletions), 0) "
        "FROM daily_stats WHERE date >= ?",
        (week_ago,),
    )
    net_lines_this_week = (await cursor.fetchone())[0]

    cursor = await db.execute(
        "SELECT COALESCE(SUM(CASE WHEN severity = 'vulnerable' THEN 1 ELSE 0 END), 0), "
        "COALESCE(SUM(CASE WHEN severity IN ('outdated', 'major') THEN 1 ELSE 0 END), 0) "
        "FROM dependencies"
    )
    vuln_total, outdated_total = await cursor.fetchone()

    kpis = {
        "total_repos": len(results),
        "repos_with_changes": sum(1 for r in results if r.get("has_uncommitted")),
        "commits_this_week": commits_this_week,
        "commits_this_month": commits_this_month,
        "net_lines_this_week": net_lines_this_week,
        "stale_branches": sum(r.get("stale_branch_count", 0) for r in results),
        "vulnerable_deps": vuln_total,
        "outdated_deps": outdated_total,
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
