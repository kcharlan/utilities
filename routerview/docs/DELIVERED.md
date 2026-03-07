# RouterView -- As-Delivered Reference (v1)

## Overview

RouterView is a single-file, self-bootstrapping Python application that provides an analytics dashboard for OpenRouter API usage. It ingests LLM generation data via OTLP broadcast, CSV import, or API polling, stores it in SQLite, and serves a React SPA with KPI cards, timeseries charts, breakdowns, a heatmap, comparison modes, and a paginated log viewer.

## Features

### Data Ingestion

- **OTLP Broadcast**: Real-time webhook receiver at `/v1/traces`. Accepts OTLP/HTTP+JSON payloads from OpenRouter. Supports connection testing via `X-Test-Connection: true` header.
- **CSV Import**: Uploads an OpenRouter Activity Export CSV. Maps fields including `generation_id`, `model_permaslug`, `cost_total`, `cost_cache`, `cost_web_search`, `cost_file_processing`, `tokens_prompt`, `tokens_completion`, `tokens_reasoning`, `tokens_cached`, `time_to_first_token_ms`, `user`, `finish_reason_normalized`, `provider_name`, `api_key_name`, `app_name`, `streamed`, `cancelled`, `num_search_results`, `generation_time_ms`. Triggers a full summary rebuild after import.
- **API Poll**: Fetches daily aggregates from the OpenRouter Activity API (`/api/v1/activity`), paginated. Writes to `daily_summaries` only (not per-request `generations`). Requires a provisioning API key stored in settings. Also fetches `/api/v1/keys` for key label resolution.
- **Deduplication**: All ingestion paths use `INSERT ... ON CONFLICT(id) DO UPDATE` (UPSERT) on the generation ID.
- **Adaptive Attribute Mapping**: OTLP attribute-to-column mapping is defined in `~/.routerview/attribute_mapping.json` with fallback chains per field. Hot-reloaded on every incoming trace (no restart needed). Falls back to built-in defaults if the file is missing or malformed.

### Dashboard

- **KPI Cards**: 6 cards -- Requests, Total Cost, Cost/Req, Latency, Cache Hit Rate, Total Tokens. Cost/Req cycles through Avg, P50, P95, Min, Max. Latency cycles through the same five aggregations. Total Cost shows a projected value for partial periods (when less than 99% of the period has elapsed). All cards show comparison deltas when comparison is enabled.
- **Time Range Picker**: Calendar-aligned presets (Today, Yesterday, This/Last Week, This/Last Month, This/Last Quarter, This/Last Year), rolling ranges (Last 1h, 6h, 24h, 7d, 30d, 90d), All Time, and Custom Range with from/to date pickers. Calendar ranges use the browser's timezone for boundary alignment.
- **Timeseries Chart**: Supports Area, Line, Bar, and Heatmap chart types. Groups by Model, Provider, API Key, or None. Auto-selects bucket size (minute/hour/day/week/month) based on range duration. Empty buckets are filled with zeroes for minute/hour/day granularity.
  - **Cumulative Toggle**: A "cumulative" button switches between per-bucket and running cumulative totals. Disables stacking when active. Not available for the latency metric.
  - **Split Comparison View**: When comparison is enabled, the chart area splits into two stacked charts (current period top, prior period bottom) with a shared Y-axis scale, independent X-axis labels, linked proportional crosshair, and a shared clickable legend.
- **Comparison Mode**: 8 modes -- Prior Period, Day-over-Day (DoD), Week-over-Week (WoW), Month-over-Month date-aligned (MoM), Month-over-Month relative weekday (MoM), Quarter-over-Quarter (QoQ), Year-over-Year date-aligned (YoY), Year-over-Year relative weekday (YoY). Prior Period is calendar-aware for named ranges (e.g., "This Month" compares against the full prior calendar month, not a shift-by-duration). Smart defaults auto-apply based on time range selection.
- **Breakdown Panels**: Three panels -- Cost by Model, Cost by API Key, Requests by Provider. Horizontal bar charts with top-20 limit. Drag-and-drop rearrangeable (order persisted to localStorage). Panel order is included in saved views. Individually exportable (CSV/SVG/PNG/JPG). Clicking a bar dimension applies it as a filter.
- **Heatmap**: Hour-of-day (0-23) x Day-of-week (Sun-Sat) usage intensity grid. Supports cost, requests, and tokens metrics. Available as a chart type selection (not a separate panel). Uses the user's timezone for hour/day alignment.
- **Filter Bar**: Multi-select dropdowns for Model, Provider, API Key, Origin, and Finish Reason. Composable (AND logic across dimensions). Searchable dropdowns (searches both display label and raw ID). Filter and comparison state synced to URL query string via `history.replaceState` for bookmarkable/shareable views.
- **Log Viewer**: Paginated table of individual generations with server-side search (searches id, model, model_short, provider_name, origin, finish_reason, api_key_label). Column sorting on created_at, model_short, provider_name, tokens_total, cost_usd, generation_time_ms, finish_reason, api_key_label. Row expansion for full detail. Editable page number input. Configurable page size (capped at 250). Anomaly flags displayed per row.
- **Saved Views**: Save and restore named dashboard configurations (time range, filters, chart type, metric, group by, panel order, compare mode, compare enabled). CRUD via header dropdown. Views are stored in SQLite with unique name constraint; saving an existing name overwrites it.
- **Keyboard Shortcuts**: `/` focuses log search, left/right arrows navigate time range presets, `R` refreshes data, `Escape` clears all filters, `?` shows shortcuts help modal. Shortcuts are suppressed when focus is in an input/textarea/select.
- **Setup Wizard**: First-run wizard shown before the main dashboard. Re-triggered when `setupComplete` state is false.

### Export

- **CSV**: Available for generations (full table dump), summary (single-row KPI snapshot), and breakdown (dimensional aggregation). Filename includes the view name and current date.
- **Image**: PNG and JPG via canvas capture at 2x resolution with dark background fill. SVG with a dark background rect inserted as the first child element.
- All exports are accessible via Export dropdown menus on the main chart and each breakdown panel.

### Settings

- OpenRouter provisioning API key configuration (displayed as masked when configured).
- Manual API poll trigger.
- Data purge by date (deletes generations and daily_summaries before a chosen date).
- Summary refresh (recent 2 days) and full summary rebuild controls.

### Real-Time

- WebSocket at `/ws` pushes new generation events on ingestion, including anomaly flags.
- 30-second heartbeat to keep connections alive.
- Client auto-reconnects with exponential backoff (starting at 1s, capped at 30s).
- Green pulsing dot indicator in the header when WebSocket is connected.
- AbortController cancels in-flight API fetches when filters or time range change rapidly.

### Anomaly Detection

- Per-model statistical baselines computed from the last 7 days of data (models with fewer than 5 generations are excluded).
- Flags generations exceeding 3 standard deviations above the mean for cost, latency, or token count.
- Anomaly flags are included in WebSocket broadcasts and log viewer rows.
- Baselines are refreshed every 15 minutes via a background task.

## Architecture

- Single Python file (3575 lines): FastAPI backend + embedded React SPA served as an HTML string.
- Self-bootstrapping: creates a venv at `~/.routerview_venv/`, installs deps, re-executes via `os.execv`.
- Dependencies: `fastapi`, `uvicorn[standard]`, `aiosqlite`, `httpx`, `python-multipart`.
- SQLite with WAL mode. Per-connection PRAGMAs: `busy_timeout=5000`, `synchronous=NORMAL`, `cache_size=-8000`.
- Frontend: React 18 + Recharts 2.13 + Tailwind CSS + Babel Standalone (all CDN, zero build step). Inline SVG icons (no icon library CDN).
- Dark theme only. ErrorBoundary wraps the entire app.
- Auto-opens browser on startup (1-second delay via threading.Timer).
- Three background tasks launched at startup via lifespan handler:
  - WebSocket heartbeat (every 30s)
  - Daily summary refresh (every 15 minutes, covers last 2 days)
  - Model anomaly stats refresh (every 15 minutes, initial 60s delay)

## Database Schema

- **`generations`** -- One row per LLM request. 28 columns including all token counts (prompt, completion, native variants, cached, reasoning), 5 cost columns (total, upstream, cache, data, web), timing (generation_time_ms, latency_ms, moderation_latency_ms), metadata (model, model_short, provider, api_key_id/label, app_id, origin, finish_reason, external_user, trace_metadata), and flags (streamed, cancelled). `tokens_total` is `GENERATED ALWAYS AS (tokens_prompt + tokens_completion) STORED`. 12 indexes including composites on (created_date, model) and (created_date, api_key_id).
- **`daily_summaries`** -- Materialized daily aggregates grouped by (date, model, provider_name, api_key_id). PK uses `TEXT NOT NULL DEFAULT ''` for nullable FK columns. Includes avg/p50/p95/p99 generation time. Rebuilt on CSV import; incrementally refreshed by background task.
- **`ingestion_log`** -- Tracks import runs with source, timestamps, record counts, and error messages.
- **`settings`** -- Key-value configuration store.
- **`saved_views`** -- Named dashboard configurations with id, name (unique), config JSON, created_at, updated_at.

## Data Files

All runtime state under `~/.routerview/`:

| File | Purpose |
|---|---|
| `routerview.db` | SQLite database |
| `attribute_mapping.json` | OTLP attribute mapping (created with defaults on first run, hot-reloaded per trace) |
| `last_port` | Last bound port number |
| `traces/` | Raw OTLP JSON payloads (debug mode only, no auto-purge) |

## API Endpoints

### Ingestion

| Method | Path | Description |
|---|---|---|
| POST | `/v1/traces` | OTLP/HTTP+JSON receiver |
| POST | `/api/import/csv` | Upload OpenRouter CSV export |
| POST | `/api/import/poll` | Trigger Activity API poll (daily_summaries only) |

### Dashboard Data

| Method | Path | Description |
|---|---|---|
| GET | `/api/summary` | Aggregated KPI metrics with optional comparison |
| GET | `/api/timeseries` | Time-bucketed series with optional comparison |
| GET | `/api/breakdown` | Dimensional breakdown (top 20) |
| GET | `/api/heatmap` | Hour x Day-of-Week matrix |
| GET | `/api/generations` | Paginated generation log with search and sort |
| GET | `/api/dimensions` | Filter dropdown values (models, providers, keys, origins, finish_reasons) |
| GET | `/api/export/csv` | CSV export of generations, summary, or breakdown data |

### System

| Method | Path | Description |
|---|---|---|
| GET | `/` | Serve React SPA (no-cache headers) |
| GET | `/ws` | WebSocket for real-time updates and heartbeat |
| GET | `/api/health` | Health check (version, generation count, DB size, connected clients) |
| GET | `/api/settings` | Read settings (API key masked) |
| PUT | `/api/settings` | Update settings |
| POST | `/api/purge` | Delete data before a given date |
| GET | `/api/views` | List saved views |
| POST | `/api/views` | Create or update a saved view (upsert on name) |
| DELETE | `/api/views/{id}` | Delete a saved view |
| POST | `/api/admin/refresh-summaries` | Refresh summaries for last 2 days |
| POST | `/api/admin/rebuild-summaries` | Full summary rebuild (requires `confirm=true`) |

All dashboard data endpoints accept common query parameters: `range`, `from`, `to`, `tz`, `model`, `provider`, `api_key`, `origin`, `finish_reason`.

## Companion Tools

- **`trace_inspect`** -- CLI tool for inspecting raw OTLP trace files saved in debug mode. Shows how trace attributes align with the attribute mapping. Usage: `./trace_inspect [file]` for a specific trace, `./trace_inspect --all` for all traces, or `./trace_inspect` with no args for the latest trace.

## CLI

```
routerview [-p PORT] [--db PATH] [--host HOST] [--tunnel | --no-tunnel] [--debug] [-h]
```

| Flag | Default | Description |
|---|---|---|
| `-p/--port` | 8100 | Preferred port (auto-increments if in use, up to 20 attempts) |
| `--db` | `~/.routerview/routerview.db` | SQLite database path |
| `--host` | 127.0.0.1 | Bind address |
| `--tunnel` | auto | Launch a Cloudflare Quick Tunnel (auto-detected if `cloudflared` is on PATH) |
| `--no-tunnel` | — | Disable automatic tunnel even if `cloudflared` is available |
| `--debug` | off | Enable OTLP payload capture to `~/.routerview/traces/` and debug-level uvicorn logging |

### Automatic Tunnel

When `cloudflared` is on PATH (or `--tunnel` is passed), RouterView automatically:

1. Spawns `cloudflared tunnel --url http://localhost:{port}` as a managed subprocess
2. Parses the Quick Tunnel URL from cloudflared's output
3. Copies the webhook URL (`{tunnel_url}/v1/traces`) to the clipboard
4. Opens `https://openrouter.ai/settings/observability` in the browser (on first run or when the URL changes)
5. Stores the tunnel URL in settings for dashboard display
6. Cleans up the cloudflared process on shutdown (Ctrl+C)

### Environment Variables

| Variable | Description |
|---|---|
| `OPENROUTER_MGMT` | OpenRouter management/provisioning API key. Auto-seeded into settings on startup if not already configured. |

## Known Limitations

- Dark theme only (no light mode).
- Single-user (no authentication or multi-tenancy).
- No alerting or notifications.
- Desktop-first layout (no mobile optimization).
- API poll imports daily aggregates only (not per-request granularity).
- No auto-purge of debug trace files.
- Timeseries grouping supports model, provider, api_key, and none -- origin and finish_reason are filter-only (not groupable in charts).
