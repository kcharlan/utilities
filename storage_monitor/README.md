# Storage Monitor

Storage Monitor is a local-first macOS disk-usage and cleanup console. It scans APFS volumes, local snapshots, caches, app data, model stores, and large user files, then presents the results in a React dashboard with graphical breakdowns, reclaim estimates, and explicit cleanup actions.

It follows the repo's self-bootstrapping local web app pattern:

- Python backend
- localhost-only FastAPI server
- embedded React SPA
- runtime home under `~/.storage_monitor/`

## Quick Start

Run the entrypoint directly:

```zsh
./storage_monitor
```

Or symlink it into your `PATH`:

```zsh
ln -s "$(pwd)/storage_monitor" /usr/local/bin/storage_monitor
storage_monitor
```

On first run, Storage Monitor creates its runtime home at `~/.storage_monitor/`, installs a private virtual environment at `~/.storage_monitor/venv/`, saves scan history locally, then launches the web UI in your browser.

## Current Capabilities

- APFS container and Data-volume accounting
- Local snapshot inventory
- Visible live data vs APFS-reported usage delta
- Top-level breakdowns for:
  - `/System/Volumes/Data`
  - `~/`
  - `~/Library`
  - `/Applications`
- Watchlist-based scanning for:
  - caches
  - model stores
  - stale installer artifacts
  - app runtime payloads
  - review-only large data buckets
- Large-file inventory under the home directory
- Safe cleanup actions:
  - move cache-like paths to `~/.Trash/`
  - move stale installer staging paths to `~/.Trash/`
  - delete individual local snapshots
  - reveal a file or directory in Finder

## Runtime State

Runtime files live under `~/.storage_monitor/`:

- `bootstrap_state.json` -- venv refresh marker
- `latest_scan.json` -- most recent completed scan
- `history/` -- dated scan snapshots
- `action_log.jsonl` -- cleanup action log
- `last_port` -- most recent port used

## Validation

Smallest relevant checks:

```zsh
./storage_monitor --help
UTILITIES_TESTING=1 STORAGE_MONITOR_HOME="$(mktemp -d)" ./storage_monitor --no-browser --port 8473
```
