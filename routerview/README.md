# RouterView

A self-hosted OpenRouter analytics dashboard for CSV imports. Import OpenRouter Activity exports into a local SQLite database, keep the history indefinitely, and analyze usage with calendar-aligned ranges, comparisons, breakdowns, exports, and a full request log.

## Quick Start

RouterView is a self-bootstrapping utility. No manual environment setup is required to run it.

1. Optional global symlink:
   ```zsh
   ln -s "$(pwd)/routerview" /usr/local/bin/routerview
   ```
2. Start the app:
   ```zsh
   routerview
   ```
3. Open Settings in the UI and import an OpenRouter Activity CSV export.

On first run RouterView creates its runtime home at `~/.routerview/` and a private venv at `~/.routerview_venv/`.

## CLI

```text
routerview [-p <port>] [--db <path_to_db>] [--host <bind_host>] [--debug]
```

- `-p`, `--port` preferred local port, default `8100`
- `--db` SQLite database path, default `~/.routerview/routerview.db`
- `--host` bind address, default `127.0.0.1`
- `--debug` verbose server logging

## Current Workflow

1. Export usage from OpenRouter as CSV.
2. Import the file through RouterView.
3. Re-import safely when needed. Duplicate `generation_id` rows are skipped and reported as skipped.
4. Explore usage with time ranges such as Today, Yesterday, This Month, or custom windows.

The dashboard refreshes immediately after a successful CSV import, including the active Today view.

## Key Features

- CSV import for OpenRouter Activity exports
- Calendar-aligned ranges and prior-period comparison modes
- KPI cards, timeseries charts, heatmap, and breakdown panels
- Multi-dimensional filters for model, provider, API key, origin, and finish reason
- Paginated generation log with search, sorting, and row expansion
- CSV and image export from dashboard views
- Saved views and keyboard shortcuts
- Local SQLite retention under your home directory

## Architecture

- Single-file Python/FastAPI backend with an embedded React SPA
- SQLite for storage
- Self-bootstrapping private venv with no repo-local install step

The current design is documented in [docs/DESIGN.md](docs/DESIGN.md).

## Documentation

- [Design Document](docs/DESIGN.md) - current CSV-only architecture and data flow
- [Setup Guide](docs/SETUP_GUIDE.md) - first-run and CSV import workflow
- [Delivered Reference](docs/DELIVERED.md) - current feature and endpoint reference

## Data Storage

RouterView stores runtime state under `~/.routerview/`:

- `bootstrap_state.json` bootstrap version and Python version marker
- `routerview.db` SQLite database
- `last_port` last bound port

The private venv lives at `~/.routerview_venv/`.
