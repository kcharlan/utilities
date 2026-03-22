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

On first run, Storage Monitor creates its runtime home at `~/.storage_monitor/`, installs a private virtual environment at `~/.storage_monitor/venv/`, creates its SQLite scan database, saves scan history locally, then launches the web UI in your browser.

## Current Capabilities

- **3-zone dashboard**: compact header bar, treemap + accordion breakdowns, tabbed action panel
- **Dark mode**: auto-detects OS preference, manual toggle, persists to localStorage
- **Progressive scan streaming**: sections populate in real-time as each scan phase completes via granular SSE events
- **Treemap visualization**: proportional CSS Grid blocks for the 4 root storage areas with click-to-expand
- **Drill-down breakdowns**: click any directory to explore its children from the durable SQLite-backed scan index, with on-demand persistence for paths that were not pre-indexed
- APFS container and Data-volume accounting
- Local snapshot inventory with dedicated manager (sort, multi-select, bulk delete)
- Visible live data vs APFS-reported usage delta
- Top-level breakdowns for:
  - `/System/Volumes/Data`
  - `~/`
  - `~/Library`
  - `/Applications`
- Watchlist-based scanning for caches, model stores, stale installers, app runtime payloads, and large data buckets
- Large-file inventory (files >= 1 GB) in a dedicated tab
- Safe cleanup actions:
  - move cache-like paths to `~/.Trash/`
  - move stale installer staging paths to `~/.Trash/`
  - delete individual or bulk local snapshots
  - reveal a file or directory in Finder
- **Immediate targeted refresh** after actions for metadata, affected breakdowns, and durable cached scan data
- Per-section staleness timestamps ("scanned Xm ago")

## Runtime State

Runtime files live under `~/.storage_monitor/`:

- `bootstrap_state.json` -- venv refresh marker
- `storage_monitor.db` -- durable scan index and cached drill-down data
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
