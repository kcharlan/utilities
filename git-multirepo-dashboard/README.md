# Git Fleet

A local multi-repo git dashboard. Track working state, commit history, branch staleness, and dependency health across all your projects in one place.

## Requirements

- **Python 3.9+**
- **git** in PATH
- At least one ecosystem dependency tool (npm, go, cargo, bundle, composer, or pip-audit)

## Quick Start

```bash
python git_dashboard.py
```

On first run, Git Fleet creates a virtual environment at `~/.git_dashboard_venv` and installs its dependencies automatically. No manual setup step required.

The dashboard opens in your browser at `http://localhost:8300`.

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

- **Venv:** `~/.git_dashboard_venv/`
- **Database:** `~/.git_dashboard/dashboard.db` (SQLite, WAL mode)

## Supported Ecosystems

| Ecosystem | Required tool | Optional tools |
|-----------|---------------|----------------|
| Python    | none (PyPI API for outdated checks) | `pip-audit` for vulnerability scanning |
| Node.js   | `npm`         | — |
| Go        | `go`          | `govulncheck` for vulnerability scanning |
| Rust      | `cargo`       | `cargo-outdated`, `cargo-audit` |
| Ruby      | `bundle`      | `bundler-audit` |
| PHP       | `composer`    | — |

## Development

Install test dependencies and run the test suite from within the app venv:

```bash
# Bootstrap the venv first
python git_dashboard.py --yes --no-browser &
sleep 3 && kill %1

# Install test deps
~/.git_dashboard_venv/bin/pip install pytest httpx

# Run tests
~/.git_dashboard_venv/bin/python -m pytest tests/ -v
```

## Cross-Platform Notes

- Works on **Windows 10+**, **macOS 12+**, and **Linux**.
- Always invoke as `python git_dashboard.py` (not `./git_dashboard.py`) for Windows compatibility.
- Paths with spaces are handled correctly via `pathlib.Path`.
