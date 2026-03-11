# Git Fleet

A local multi-repo git dashboard built for monorepos and multi-project setups. Track working state, commit history, branch staleness, and dependency health across all your projects from a single browser tab.

## Quick Start

```bash
python git_dashboard.py
```

On first run, Git Fleet creates a virtual environment at `~/.git_dashboard_venv/` and installs its dependencies automatically. No manual setup required. The dashboard opens in your browser at `http://localhost:8300`.

To register a directory of repos on launch:

```bash
python git_dashboard.py --scan ~/source/my-projects
```

## Requirements

- **Python 3.9+**
- **git** in PATH

Optional ecosystem tools enable dependency health checking. Git Fleet runs without them but warns on startup:

| Ecosystem | Outdated checks | Vulnerability scanning |
|-----------|-----------------|------------------------|
| Python    | PyPI JSON API (built-in) | `pip-audit` |
| Node.js   | `npm outdated` | `npm audit` |
| Go        | `go list -m -u` | `govulncheck` |
| Rust      | `cargo-outdated` | `cargo-audit` |
| Ruby      | `bundle outdated` | `bundler-audit` |
| PHP       | `composer outdated` | `composer audit` |

## Features

### Fleet Overview
Browse all registered repos at a glance. Each card shows current branch, last commit, uncommitted change counts, and a 13-week activity sparkline. KPI tiles summarize fleet-wide commit velocity and branch health. Cards with missing disk paths or scan errors are flagged visually.

### Directory Browser
A built-in file browser lets you navigate your filesystem and register directories without touching the command line. Git repos are identified with visual indicators. Click **Scan Dir** in the header to open.

### Full Scan
Runs three passes across all registered repos:

1. **History scan** — aggregates `git log` into daily commit/insertion/deletion stats (incremental; only fetches new data on subsequent runs)
2. **Branch scan** — lists all local branches, marks stale branches (>30 days since last commit), identifies the default branch
3. **Dependency scan** — detects manifest files (`requirements.txt`, `package.json`, `go.mod`, `Cargo.toml`, `Gemfile`, `composer.json`) up to 3 directories deep, parses dependencies, and runs ecosystem health checks

Progress streams in real time via SSE to a toast notification in the UI.

### Monorepo Support
Dependency detection walks subdirectories (up to 3 levels), so monorepos with multiple projects are fully supported. Each dependency tracks its `source_path` — the relative path to the manifest file it came from (e.g., `web_games/multibody_sim/package.json`). The Dependencies tab groups packages by manifest location so you can tell exactly which sub-project owns each dependency.

### Repo Detail View
Click any repo card to drill into four sub-tabs:

- **Activity** — daily commit chart with configurable time ranges (30d / 90d / 180d / 1y / All)
- **Commits** — paginated commit history with hash, date, message, and diffstat
- **Branches** — all local branches with last commit date and stale/active/default badges
- **Dependencies** — packages grouped by ecosystem and source path, with outdated/vulnerable severity indicators and a **Check Now** button for on-demand re-scan

### Analytics
Fleet-wide analytics across all repos:

- **Commit heatmap** — calendar-style daily commit volume
- **Time allocation** — commit distribution across repos
- **Dependency overlap** — packages shared across multiple repos with version spread

### Delete & Cleanup
Hover any repo card to reveal the delete button. Removing a repo deletes all associated data (branches, dependencies, scan history) via cascading foreign keys.

## Usage

```
python git_dashboard.py [options]

Options:
  --port N       Port to listen on (default: 8300; auto-increments if in use)
  --no-browser   Skip opening a browser tab on startup
  --scan PATH    Register and scan a directory on startup
  --yes, -y      Skip missing-tools confirmation prompt (for scripted launches)
  --help         Show this message and exit
```

## Data Storage

| Item | Location |
|------|----------|
| Runtime venv | `~/.git_dashboard_venv/` |
| Database | `~/.git_dashboard/dashboard.db` (SQLite, WAL mode) |

The database path can be overridden with the `GIT_DASHBOARD_DB` environment variable.

## Architecture

Single-file self-bootstrapping Python application (`git_dashboard.py`). The backend is FastAPI + uvicorn with aiosqlite for async database access. The frontend is a React 18 SPA loaded via CDN (React, ReactDOM, Babel Standalone, Recharts) — no build step, no `node_modules`. All JSX is embedded in the Python file as a template string served from `GET /`.

### Database Schema

Six tables with cascading foreign keys:

- **repositories** — registered repos with path, detected runtime, default branch
- **working_state** — current status snapshot (uncommitted changes, current branch, scan errors)
- **daily_stats** — historical commit/insertion/deletion rollups by date
- **branches** — branch names, last commit dates, staleness flags
- **dependencies** — parsed manifest entries with version, severity, advisory, and source path
- **scan_log** — scan execution history (type, status, timing, repos scanned)

## Development

A local `.venv/` in the project root holds test-only dependencies, separate from the runtime venv at `~/.git_dashboard_venv/`.

```bash
# Create test venv and install deps
python3 -m venv .venv
.venv/bin/pip install pytest httpx aiosqlite fastapi packaging

# Run unit tests
.venv/bin/python -m pytest tests/ --ignore=tests/test_e2e.py -v

# Run E2E tests (requires Playwright)
.venv/bin/pip install playwright pytest-playwright
.venv/bin/playwright install chromium
.venv/bin/python -m pytest tests/test_e2e.py -v
```

E2E tests must run in a separate pytest invocation from unit tests (Playwright's event loop conflicts with `asyncio.run()`). The E2E test server uses an isolated temp database so test repos never pollute user data.

## Cross-Platform Notes

- Works on **Windows 10+**, **macOS 12+**, and **Linux**.
- Always invoke as `python git_dashboard.py` (not `./git_dashboard.py`) for Windows compatibility.
- Paths with spaces are handled correctly via `pathlib.Path`.
