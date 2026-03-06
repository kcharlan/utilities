# RouterView

A self-hosted OpenRouter analytics dashboard with real-time observability, deep cost analysis, and full historical data retention -- everything the official OpenRouter dashboard should be but isn't.

## Quick Start

RouterView is a **self-bootstrapping** utility. No manual environment setup required.

1. **Make it Global (Optional):**
   ```zsh
   ln -s "$(pwd)/routerview" /usr/local/bin/routerview
   ```

2. **Run:** Just launch it. On the first run, it will automatically set up its own hidden environment in `~/.routerview_venv`.
   ```zsh
   routerview
   ```

3. **Options:**
   ```
   routerview [-p <port>] [--db <path_to_db>]
   ```
   - `-p`, `--port` -- port for the local server (default: 8100)
   - `--db` -- path to the SQLite database (default: `~/.routerview/routerview.db`)

## Setup

RouterView needs a tunnel (to receive data from OpenRouter) and a one-time Broadcast configuration in your OpenRouter account. See [docs/SETUP_GUIDE.md](docs/SETUP_GUIDE.md) for the full walkthrough.

## Architecture

Single-file Python/FastAPI backend with an embedded React SPA. SQLite for storage. Self-bootstrapping venv -- no `pip install`, no `npm`. See [docs/DESIGN.md](docs/DESIGN.md) for the full design document.

## Key Features

### Real-Time Ingestion

- OTLP/HTTP+JSON receiver for OpenRouter Observability Broadcast
- Adaptive attribute mapping with hot-reloadable external config
- CSV import (OpenRouter Activity Export)
- API polling for daily summary backfill

### Analytics Dashboard

- 6 KPI cards with comparison deltas and aggregation cycling
- Timeseries chart (area/line/bar) with auto-bucketing
- Split comparison view: two charts with shared scale and linked crosshair
- Cumulative toggle for running totals (cost tracking vs prior periods)
- 8 comparison modes with calendar-aware prior period
- Breakdown panels (cost by model, cost by API key, requests by provider)
- Usage heatmap (hour x day-of-week)
- Multi-dimensional filtering (model, provider, API key, origin, finish reason)

### Log Viewer

- Paginated generation log with server-side search
- Column sorting, row expansion for full detail
- First/Last navigation, editable page number

### Export

- CSV export from any view
- Image export: PNG, JPG, SVG (with dark background)

### Customization

- Saved views (named dashboard configurations)
- Drag-and-drop panel reordering
- Keyboard shortcuts (left/right time nav, R refresh, Esc clear, ? help)
- Dark theme throughout

## Companion Tools

- `trace_inspect` -- CLI tool for inspecting OTLP traces and verifying attribute mapping alignment

## Documentation

- [Design Document](docs/DESIGN.md) -- architecture, schema, API design
- [Setup Guide](docs/SETUP_GUIDE.md) -- installation, tunnel setup, OpenRouter Broadcast config
- [Delivered Reference](docs/DELIVERED.md) -- complete feature reference and API listing

## Data Storage

All runtime state under `~/.routerview/`:
- `routerview.db` -- SQLite database
- `attribute_mapping.json` -- OTLP attribute mapping
- `traces/` -- raw payloads (debug mode only)

Venv at `~/.routerview_venv/`.
