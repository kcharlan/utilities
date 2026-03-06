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

See [docs/DESIGN.md](docs/DESIGN.md) for the full design document.

## Key Features

- **Real-time ingestion** via OpenRouter's Observability Broadcast (webhook/OTLP)
- **Indefinite local retention** in SQLite (no 30-day limit)
- **SRE-grade dashboard** with live-updating charts and metrics
- **Multi-dimensional slicing**: model, provider, API key, time range, cost, latency
- **Calendar-aligned time ranges**: day/week/month on actual boundaries, not rolling windows
- **Export anything**: CSV, PNG, SVG, JPG from any view
- **Log viewer**: browse, filter, search, and export individual request logs
- **Self-bootstrapping**: single command to run, no manual dependency management
