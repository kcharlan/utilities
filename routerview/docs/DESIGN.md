# RouterView -- Design Document

## 1. Overview

RouterView is a self-hosted OpenRouter analytics dashboard that replaces the official OpenRouter Activity page with a dramatically superior experience. It provides real-time data ingestion, indefinite local retention, deep multi-dimensional analytics, and an SRE-grade live dashboard.

### 1.1 Why This Exists

The official OpenRouter dashboard has critical limitations:

- **Time ranges are relative, not calendar-aligned.** "1 day" means "last 24 hours from now," not "today." Same for week, month, etc. This makes cost accounting and period-over-period comparison unreliable.
- **Filtering is primitive.** You can group by model OR API key, but not slice across multiple dimensions simultaneously.
- **Data retention is 30 days.** No way to do quarterly or annual analysis.
- **No export of views.** You can export raw CSV but not the charts or filtered views you're looking at.
- **Missing data.** The dashboard doesn't surface provider, latency, cache hits, reasoning tokens, or other fields that the API actually tracks.

### 1.2 Goals

1. Real-time data ingestion -- every OpenRouter request appears in RouterView within seconds.
2. Indefinite local data retention in SQLite with optional purge.
3. Calendar-aligned time boundaries for all aggregations.
4. Multi-dimensional filtering and grouping (model + provider + API key + time, simultaneously).
5. SRE-grade live dashboard with auto-refreshing charts and metrics.
6. Export any view as CSV, PNG, SVG, or JPG.
7. Full request log browser with search, filter, and export.
8. Surface every data field OpenRouter provides -- nothing hidden.

### 1.3 Non-Goals (v1)

- Alerting/notification system (future enhancement).
- Multi-user auth or team management.
- Direct OpenRouter API proxy functionality.
- Mobile-optimized layout (desktop-first, responsive as a bonus).

---

## 2. Architecture

### 2.1 Tech Stack

Following the repository standard (see CLAUDE.md "Preferred Patterns for New Projects"):

| Layer | Technology | Rationale |
|---|---|---|
| Backend | Python 3.10+, FastAPI, uvicorn | Repo standard. Self-bootstrapping pattern from editdb. |
| Frontend | React 18 (CDN), Tailwind CSS, Babel Standalone | Repo standard. Single-file embedded SPA, zero build step. |
| Database | SQLite (via Python `sqlite3`) | Lightweight, zero-config, file-based. Perfect for local analytics. |
| Charting | Recharts (React, CDN) | Already available in the repo's CDN stack. Declarative, composable. |
| Real-time | WebSocket (FastAPI native) | Push DB changes to frontend instantly. |
| Data ingestion | OTLP/HTTP+JSON receiver | Receives OpenRouter Broadcast webhook traces. |
| Tunnel (optional) | Cloudflare Tunnel or ngrok | Exposes local OTLP endpoint to OpenRouter's broadcast system. |

### 2.2 System Diagram

```
OpenRouter Cloud                         Local Machine
+---------------------+                  +----------------------------------+
|                     |                  |         RouterView               |
|  Your LLM requests  |                  |                                  |
|  (from any app)     |                  |  +----------------------------+  |
|         |           |                  |  |  FastAPI Backend           |  |
|         v           |                  |  |                            |  |
|  OpenRouter API     |   OTLP/HTTP      |  |  /v1/traces  (OTLP recv)   |  |
|         |           | ----------------->  |  /api/*      (REST API)    |  |
|  Observability      |   (via tunnel    |  |  /ws         (WebSocket)   |  |
|  Broadcast          |    or direct)    |  |       |                    |  |
+---------------------+                  |  |       v                    |  |
                                         |  |  SQLite DB                 |  |
                                         |  |  (~/.routerview/           |  |
                                         |  |   routerview.db)           |  |
                                         |  +----------------------------+  |
                                         |                                  |
                                         |  +----------------------------+  |
                                         |  |  React SPA (embedded)      |  |
                                         |  |                            |  |
                                         |  |  Dashboard    Log Viewer   |  |
                                         |  |  Charts       Export       |  |
                                         |  |  Filters      Settings     |  |
                                         |  +----------------------------+  |
                                         +----------------------------------+
```

### 2.3 Data Flow

1. **Ingestion**: OpenRouter Broadcast sends OTLP/HTTP+JSON traces to RouterView's `/v1/traces` endpoint.
2. **Parsing**: The backend extracts span attributes from the OTLP payload (gen_ai.* semantic conventions) and maps them to the local schema.
3. **Storage**: Parsed records are inserted into SQLite with full indexing.
4. **Notification**: On each new insert, a WebSocket message is broadcast to all connected frontend clients.
5. **Display**: The React frontend receives the WebSocket event, updates in-memory state, and re-renders affected charts/tables without full page reload.

### 2.4 Fallback Ingestion

If the webhook/tunnel approach is not viable for a given deployment, RouterView also supports:

- **Manual CSV import**: Upload an OpenRouter Activity Export CSV.
- **API polling**: Scheduled pull from `/api/v1/activity` using a provisioning key (daily aggregates, last 30 days). Useful for backfilling historical data.

Both fallback methods write to the same SQLite schema and are fully compatible with the dashboard.

---

## 3. Data Model

### 3.1 SQLite Schema

#### `generations` table (primary data)

This is the core table. One row per LLM generation (request/response pair).

```sql
CREATE TABLE generations (
    id                          TEXT PRIMARY KEY,   -- OpenRouter generation_id (e.g., "gen-...")
    created_at                  TEXT NOT NULL,       -- ISO 8601 timestamp with timezone
    created_date                TEXT NOT NULL,       -- YYYY-MM-DD (derived, for fast date grouping)
    created_hour                INTEGER NOT NULL,    -- 0-23 (derived, for hourly aggregation)

    -- Model and routing
    model                       TEXT NOT NULL,       -- e.g., "anthropic/claude-sonnet-4-20250514"
    model_short                 TEXT NOT NULL,       -- e.g., "claude-sonnet-4" (derived, human-friendly)
    provider_name               TEXT,                -- e.g., "Anthropic", "AWS Bedrock"
    app_id                      TEXT,                -- OpenRouter app ID

    -- API key identification
    api_key_id                  TEXT,                -- Key identifier (not the secret)
    api_key_label               TEXT,                -- Human-readable key label if available

    -- Token usage
    tokens_prompt               INTEGER DEFAULT 0,
    tokens_completion           INTEGER DEFAULT 0,
    tokens_total                INTEGER GENERATED ALWAYS AS (tokens_prompt + tokens_completion) STORED,
    native_tokens_prompt        INTEGER DEFAULT 0,
    native_tokens_completion    INTEGER DEFAULT 0,
    native_tokens_reasoning     INTEGER DEFAULT 0,
    native_tokens_cached        INTEGER DEFAULT 0,

    -- Media (multimodal)
    num_media_prompt            INTEGER DEFAULT 0,
    num_input_audio_prompt      INTEGER DEFAULT 0,
    num_media_completion        INTEGER DEFAULT 0,

    -- Cost (USD)
    cost_usd                    REAL DEFAULT 0.0,    -- Total cost for this generation
    cost_upstream_usd           REAL DEFAULT 0.0,    -- Upstream provider cost
    cost_cache_usd              REAL DEFAULT 0.0,    -- Cache-related cost
    cost_data_usd               REAL DEFAULT 0.0,    -- Data/file cost component
    cost_web_usd                REAL DEFAULT 0.0,    -- Web search cost component

    -- Performance
    generation_time_ms          INTEGER,             -- Time to generate (milliseconds)
    latency_ms                  INTEGER,             -- Total latency including network
    moderation_latency_ms       INTEGER,             -- Moderation check time

    -- Request metadata
    streamed                    BOOLEAN DEFAULT 0,
    cancelled                   BOOLEAN DEFAULT 0,
    finish_reason               TEXT,                -- "stop", "length", "tool_calls", etc.
    origin                      TEXT,                -- Origin URL of the request
    external_user               TEXT,                -- External user identifier if set

    -- Search
    num_search_results          INTEGER DEFAULT 0,

    -- Custom trace metadata (JSON blob for extensibility)
    trace_metadata              TEXT,                -- JSON string of custom trace.metadata.* attrs

    -- Internal bookkeeping
    ingestion_source            TEXT NOT NULL DEFAULT 'broadcast',  -- 'broadcast', 'api_poll', 'csv_import'
    ingested_at                 TEXT NOT NULL         -- When RouterView received this record
);
```

#### Indexes

```sql
CREATE INDEX idx_gen_created_date ON generations(created_date);
CREATE INDEX idx_gen_created_at ON generations(created_at);
CREATE INDEX idx_gen_model ON generations(model);
CREATE INDEX idx_gen_model_short ON generations(model_short);
CREATE INDEX idx_gen_provider ON generations(provider_name);
CREATE INDEX idx_gen_api_key ON generations(api_key_id);
CREATE INDEX idx_gen_cost ON generations(cost_usd);
CREATE INDEX idx_gen_origin ON generations(origin);
CREATE INDEX idx_gen_date_model ON generations(created_date, model);
CREATE INDEX idx_gen_date_key ON generations(created_date, api_key_id);
```

#### `daily_summaries` table (materialized aggregation)

Pre-computed daily rollups for fast dashboard rendering. Rebuilt on ingestion.

```sql
CREATE TABLE daily_summaries (
    date                TEXT NOT NULL,       -- YYYY-MM-DD
    model               TEXT NOT NULL,
    provider_name       TEXT,
    api_key_id          TEXT,

    request_count       INTEGER DEFAULT 0,
    tokens_prompt       INTEGER DEFAULT 0,
    tokens_completion   INTEGER DEFAULT 0,
    tokens_total        INTEGER DEFAULT 0,
    native_tokens_cached INTEGER DEFAULT 0,
    native_tokens_reasoning INTEGER DEFAULT 0,
    cost_usd            REAL DEFAULT 0.0,
    avg_generation_ms   REAL DEFAULT 0.0,
    p50_generation_ms   REAL,
    p95_generation_ms   REAL,
    p99_generation_ms   REAL,
    cancelled_count     INTEGER DEFAULT 0,
    streamed_count      INTEGER DEFAULT 0,

    PRIMARY KEY (date, model, COALESCE(provider_name, ''), COALESCE(api_key_id, ''))
);
```

#### `ingestion_log` table (operational)

Tracks ingestion runs for debugging and deduplication.

```sql
CREATE TABLE ingestion_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT NOT NULL,       -- 'broadcast', 'api_poll', 'csv_import'
    started_at      TEXT NOT NULL,
    completed_at    TEXT,
    records_received INTEGER DEFAULT 0,
    records_inserted INTEGER DEFAULT 0,
    records_skipped  INTEGER DEFAULT 0,  -- duplicates
    error_message   TEXT,
    metadata        TEXT                 -- JSON blob for source-specific info
);
```

#### `settings` table (configuration)

```sql
CREATE TABLE settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

Settings stored here include: OpenRouter provisioning API key (encrypted at rest), tunnel configuration, polling schedule, dashboard defaults, and theme preference.

### 3.2 OTLP Trace Parsing

OpenRouter sends OTLP/HTTP+JSON payloads following OpenTelemetry GenAI semantic conventions. The parser must:

1. Accept POST to `/v1/traces` with `Content-Type: application/json`.
2. Handle the test connection probe (empty payload with `X-Test-Connection: true` header) by returning 200.
3. Extract `resourceSpans[].scopeSpans[].spans[]` from the OTLP envelope.
4. Map span attributes to the `generations` table columns:
   - `gen_ai.request.model` or `gen_ai.response.model` to `model`
   - `gen_ai.usage.prompt_tokens` to `tokens_prompt`
   - `gen_ai.usage.completion_tokens` to `tokens_completion`
   - `gen_ai.response.finish_reasons` to `finish_reason`
   - `llm.provider` or similar to `provider_name`
   - `trace.metadata.*` to `trace_metadata` JSON
   - Span `startTimeUnixNano` / `endTimeUnixNano` for timing
5. Deduplicate by generation ID (upsert).
6. Return 200 on success, 400 on parse error, 500 on internal error.

**Important**: The exact attribute names will need to be verified against a live OTLP payload from OpenRouter. The first implementation milestone should include a payload capture mode that logs raw OTLP JSON to a file for schema discovery.

---

## 4. API Design

### 4.1 Ingestion Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/v1/traces` | OTLP/HTTP+JSON receiver for OpenRouter Broadcast |
| POST | `/api/import/csv` | Upload OpenRouter Activity Export CSV |
| POST | `/api/import/poll` | Trigger a manual API poll (requires provisioning key in settings) |

### 4.2 Dashboard Data Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/summary` | Aggregated metrics for a time range with filters |
| GET | `/api/timeseries` | Time-bucketed data for charts (supports minute/hour/day/week/month buckets) |
| GET | `/api/breakdown` | Grouped breakdown by dimension (model, provider, key, origin) |
| GET | `/api/generations` | Paginated generation log with full filtering |
| GET | `/api/generation/{id}` | Single generation detail |
| GET | `/api/export/csv` | Export current filtered view as CSV |
| GET | `/api/export/chart` | Export current chart as PNG/SVG/JPG (server-side rendering) |
| GET | `/api/dimensions` | List all known models, providers, keys, origins (for filter dropdowns) |

### 4.3 System Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/` | Serve the React SPA |
| GET | `/ws` | WebSocket for real-time updates |
| GET | `/api/settings` | Get current settings |
| PUT | `/api/settings` | Update settings |
| GET | `/api/health` | Health check |
| GET | `/api/ingestion-log` | Recent ingestion activity |
| POST | `/api/purge` | Purge data older than a given date |

### 4.4 Query Parameter Conventions

All dashboard data endpoints accept these common parameters:

- `from` / `to` -- ISO 8601 timestamps or date strings (YYYY-MM-DD). Always interpreted as calendar boundaries.
- `range` -- Shorthand: `today`, `yesterday`, `this_week`, `last_week`, `this_month`, `last_month`, `this_quarter`, `last_quarter`, `this_year`, `last_year`, `last_7d`, `last_30d`, `last_90d`, `all`. Calendar-aligned versions are the default; rolling versions explicitly labeled.
- `model` -- Filter by model (comma-separated for multiple).
- `provider` -- Filter by provider name.
- `api_key` -- Filter by API key ID.
- `origin` -- Filter by request origin.
- `bucket` -- Time bucket size for timeseries: `minute`, `hour`, `day`, `week`, `month`.
- `group_by` -- Dimension(s) for breakdown: `model`, `provider`, `api_key`, `origin`, `model+provider`, `model+api_key`, etc.

---

## 5. Frontend Design

### 5.1 Design Philosophy

The dashboard should feel like a professional observability tool (Datadog, Grafana) not a CRUD admin panel. Key principles:

- **Dark theme by default** with light mode toggle. Dark backgrounds make colorful charts pop and reduce eye strain during monitoring.
- **Information density over whitespace.** Every pixel should earn its place. Dense, scannable layouts with clear visual hierarchy.
- **Immediate interactivity.** Click any chart segment to drill down. Hover for details. Select time ranges by click-dragging on charts. All filters update all panels simultaneously.
- **Zero-latency feel.** Optimistic UI updates. Skeleton loaders. WebSocket-driven refresh with no polling flicker.

### 5.2 Layout Structure

```
+------------------------------------------------------------------+
|  HEADER BAR                                                       |
|  [RouterView logo]  [Time Range Picker]  [Filter Bar]  [Settings] |
+------------------------------------------------------------------+
|                                                                   |
|  KPI CARDS (top row, 5-6 cards)                                   |
|  +----------+ +----------+ +----------+ +----------+ +----------+ |
|  | Total    | | Total    | | Avg Cost | | Avg      | | Cache    | |
|  | Requests | | Cost     | | /Request | | Latency  | | Hit Rate | |
|  | 12,847   | | $142.56  | | $0.011   | | 1.2s     | | 34.2%    | |
|  | +14% WoW | | +8% WoW  | | -3% WoW  | | -12% WoW | | +5% WoW  | |
|  +----------+ +----------+ +----------+ +----------+ +----------+ |
|                                                                   |
|  MAIN CHART AREA (large, prominent)                               |
|  +--------------------------------------------------------------+ |
|  | Cost Over Time (stacked area, colored by model)              | |
|  | [Export: CSV | PNG | SVG | JPG]                [Chart Type v]| |
|  |                                                              | |
|  |    $8 |     ____                                             | |
|  |    $6 |   _/    \___    ___                                  | |
|  |    $4 |__/          \__/   \____                             | |
|  |    $2 |                         \___                         | |
|  |     0 +-----|-----|-----|-----|-----                         | |
|  |        Mon   Tue   Wed   Thu   Fri                           | |
|  |                                                              | |
|  | [Click-drag to zoom] [Double-click to reset]                 | |
|  +--------------------------------------------------------------+ |
|                                                                   |
|  BREAKDOWN PANELS (2-3 column grid, each independently sortable)  |
|  +--------------------+ +--------------------+ +-----------------+|
|  | Cost by Model      | | Cost by API Key    | | Requests by    | |
|  | (horizontal bar)   | | (horizontal bar)   | | Provider       | |
|  |                    | |                    | | (donut chart)  | |
|  | claude-sonnet  $82 | | prod-key     $95  | |                 | |
|  | gpt-4o         $34 | | dev-key      $31  | | [Anthropic 64%] | |
|  | claude-haiku   $18 | | test-key     $12  | | [Google    22%] | |
|  | gemini-pro      $8 | | personal      $4  | | [OpenAI    14%] | |
|  +--------------------+ +--------------------+ +----------------+ |
|                                                                   |
|  DETAILED TABLE / LOG VIEWER (bottom, collapsible)                |
|  +--------------------------------------------------------------+ |
|  | [Search...] [Columns v] [Export CSV] [Export filtered]       | |
|  |--------------------------------------------------------------| |
|  | Time       | Model          | Tokens | Cost   | Latency | .. | |
|  | 14:32:01   | claude-sonnet  | 4,521  | $0.04  | 1.8s    |    | |
|  | 14:31:58   | gpt-4o         | 2,103  | $0.02  | 0.9s    |    | |
|  | 14:31:45   | claude-haiku   | 891    | $0.001 | 0.3s    |    | |
|  | ...        | ...            | ...    | ...    | ...     |    | |
|  +--------------------------------------------------------------+ |
+------------------------------------------------------------------+
```

### 5.3 KPI Cards

The top row shows key performance indicators for the selected time range. Each card includes:

- **Primary metric** (large number).
- **Comparison delta** vs. prior equivalent period (e.g., "this week vs last week"), shown as percentage with color coding (green = good, red = bad; polarity depends on metric -- lower cost is green, higher cache rate is green).
- **Sparkline** (tiny inline chart showing the trend over the selected range).

KPI cards for v1:

1. **Total Requests** -- count of generations.
2. **Total Cost** -- sum of `cost_usd`.
3. **Cost / Request** -- default: mean. Supports aggregation toggle (see below).
4. **Latency** -- default: mean `generation_time_ms`. Supports aggregation toggle.
5. **Cache Hit Rate** -- `SUM(native_tokens_cached) / SUM(native_tokens_prompt)` as percentage.
6. **Total Tokens** -- sum of `tokens_total`.

#### Aggregation Toggle on KPI Cards

Cards 3 (Cost/Request) and 4 (Latency) display a clickable aggregation label (e.g., "Avg") beneath or beside the primary metric. Clicking it cycles through:

**Avg** > **P50** (median) > **P95** > **Min** > **Max**

Behavior:
- The label text updates to show the current aggregation (e.g., "P95 Latency" or "Min Cost/Req").
- The primary number, sparkline, and comparison delta all update to reflect the selected aggregation.
- Each card's selection is independent -- you can view Avg cost alongside P95 latency.
- The selection persists in localStorage so it survives page refresh.
- On hover, a tooltip shows all five values at once for quick reference without cycling.

Implementation: All five aggregations are computed in a single API response from `/api/summary`. The SQL is straightforward -- min/max/avg are native SQLite functions. P50 and P95 use window functions or subqueries:

```sql
-- For percentiles (e.g., P95 latency for the selected time range):
SELECT generation_time_ms
FROM generations
WHERE created_at BETWEEN :from AND :to
ORDER BY generation_time_ms
LIMIT 1
OFFSET (SELECT CAST(COUNT(*) * 0.95 AS INTEGER)
        FROM generations
        WHERE created_at BETWEEN :from AND :to);
```

For large datasets, the `daily_summaries` table pre-computes p50/p95/p99 during the hourly background refresh, so the dashboard doesn't need to scan the full `generations` table for historical ranges.

Cards 1, 2, 5, and 6 are inherently aggregate (total count, total sum, ratio) where percentiles don't apply, so they don't get the toggle.

### 5.4 Time Range Picker

This is a first-class component that addresses the #1 complaint about OpenRouter's dashboard.

**Calendar-aligned presets** (default behavior):

- Today, Yesterday
- This Week (Mon-Sun), Last Week
- This Month, Last Month
- This Quarter, Last Quarter
- This Year, Last Year
- All Time

**Rolling presets** (explicitly labeled as rolling):

- Last 1 hour, Last 6 hours, Last 24 hours
- Last 7 days (rolling), Last 30 days (rolling), Last 90 days (rolling)

**Custom date/time range**: A dual date-time picker for arbitrary `from` and `to` boundaries. Both date and time are selectable (not just date), so users can zoom into specific windows like "March 5, 2:00 PM to March 5, 4:30 PM." The picker pre-fills with the current selection when opened (so switching from a preset to custom doesn't lose context). Recently used custom ranges are saved for quick re-selection.

**Comparison controls**: A toggle + dropdown pair.

The **toggle** (checkbox or switch) turns comparison overlay on/off. When enabled, a **dropdown** next to it selects the comparison mode. The dropdown auto-selects a sensible default based on the current time range (e.g., "This Week" defaults to "vs Last Week"), but the user can override it.

#### Comparison Modes

| Mode | Label | How the comparison window is computed |
|---|---|---|
| Prior period | vs Prior Period | Shift back by the exact duration of the selected range. "March 1-7" compares to "Feb 22-28." This is the default for custom date ranges. |
| Day over Day | vs Same Day Last Week | Compare each day to the same weekday one week prior. Tuesday March 3 compares to Tuesday Feb 24. |
| Week over Week | vs Last Week | Compare the selected week to the prior calendar week. Always Mon-Sun to Mon-Sun. |
| Month over Month (date) | vs Same Date Last Month | March 6 compares to Feb 6. Clamps to month end if needed (March 31 compares to Feb 28). |
| Month over Month (relative) | vs Same Weekday Last Month | "1st Tuesday of March" compares to "1st Tuesday of February." Computed as: find which occurrence of the weekday this date falls on (1st, 2nd, 3rd, etc.), then find that same occurrence in the prior month. |
| Quarter over Quarter | vs Same Day Last Quarter | March 6 (day 6 of Q1) compares to Dec 6 (day 6 of Q4 prior year). |
| Year over Year (date) | vs Same Date Last Year | March 6, 2026 compares to March 6, 2025. Handles leap years (Feb 29 falls back to Feb 28). |
| Year over Year (relative) | vs Same Weekday Last Year | "1st Friday of March 2026" compares to "1st Friday of March 2025." Same Nth-weekday-of-month logic as MoM relative. |

#### Smart Defaults

The comparison dropdown auto-selects based on the active time range:

| Active time range | Default comparison |
|---|---|
| Today / Yesterday | vs Same Day Last Week |
| This Week / Last Week | vs Last Week (WoW) |
| This Month / Last Month | vs Same Date Last Month |
| This Quarter / Last Quarter | vs Same Day Last Quarter |
| This Year / Last Year | vs Same Date Last Year |
| Rolling (1h, 6h, 24h) | vs Prior Period |
| Rolling (7d, 30d, 90d) | vs Prior Period |
| Custom range | vs Prior Period |
| All Time | Comparison disabled (no meaningful prior) |

#### UI Behavior

- **On charts**: The comparison period renders as a semi-transparent overlay (same colors, 30% opacity) or as dashed lines behind the primary series. A legend entry indicates the comparison window (e.g., "Feb 24 - Mar 2" in lighter text).
- **On KPI cards**: The comparison delta (e.g., "+14% WoW") updates to reflect the selected comparison mode. The label abbreviation changes accordingly: "DoD", "WoW", "MoM", "QoQ", "YoY", or "vs prior."
- **On breakdown panels**: Each bar shows a small ghost bar behind it representing the comparison period value, with a delta label.
- The comparison mode selection persists in localStorage and in the URL query string (`compare=mom_date`).

#### Implementation: Nth-Weekday-of-Month Computation

For the "relative" MoM and YoY modes, the backend computes the comparison date as follows:

```python
from calendar import monthcalendar

def nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> int | None:
    """Return the day-of-month for the Nth occurrence of weekday in the given month.
    weekday: 0=Mon ... 6=Sun. n: 1-based (1st, 2nd, 3rd...).
    Returns None if the month doesn't have that many occurrences."""
    count = 0
    for week in monthcalendar(year, month):
        if week[weekday] != 0:
            count += 1
            if count == n:
                return week[weekday]
    return None  # e.g., no 5th Monday in February

def which_occurrence(year: int, month: int, day: int) -> tuple[int, int]:
    """Given a date, return (weekday, nth) -- e.g., (1, 2) means '2nd Tuesday'."""
    import datetime
    dt = datetime.date(year, month, day)
    weekday = dt.weekday()
    # Count how many times this weekday has occurred up to and including this day
    n = (day - 1) // 7 + 1
    return weekday, n
```

This is clean to implement and handles edge cases: if the comparison month doesn't have a 5th Tuesday (for example), it falls back to the last occurrence of that weekday in the month.

All time boundaries use the user's local timezone for calendar alignment. UTC is used only for storage.

### 5.5 Filter Bar

A horizontal bar of filter dropdowns, each populated from the `dimensions` API:

- **Model** (multi-select with search, shows model_short)
- **Provider** (multi-select)
- **API Key** (multi-select, shows label if available, otherwise truncated key ID)
- **Origin** (multi-select)
- **Finish Reason** (multi-select: stop, length, tool_calls, error, cancelled)

Filters are composable: selecting "claude-sonnet" in Model AND "prod-key" in API Key shows only that intersection.

Active filters are shown as dismissible chips. A "Clear All" button resets everything.

Filter state is preserved in the URL query string so filtered views are shareable/bookmarkable.

### 5.6 Main Chart Area

The largest visual element. Supports multiple chart types, switchable via dropdown:

1. **Stacked Area** (default for cost over time) -- each model/provider/key is a colored layer.
2. **Line Chart** -- for latency, tokens/sec, or single-metric trends.
3. **Bar Chart** -- for period comparisons or discrete categories.
4. **Heatmap** -- hour-of-day vs. day-of-week usage intensity.

Chart interactions:

- **Click-drag to zoom** into a time range. Double-click to reset.
- **Hover** shows tooltip with exact values for all series at that point.
- **Click legend items** to toggle series visibility.
- **Export button** in chart header: CSV (underlying data), PNG, SVG, JPG.

The Y-axis metric is selectable: Cost ($), Requests (#), Tokens, Latency (ms), Tokens/sec.

The time bucket auto-adjusts based on the selected range (minutes for hours, hours for days, days for weeks/months) but can be manually overridden.

### 5.7 Breakdown Panels

A grid of 2-3 smaller chart panels showing dimensional breakdowns:

- **Cost by Model** (horizontal bar chart, sorted descending).
- **Cost by API Key** (horizontal bar chart).
- **Requests by Provider** (donut/pie chart).
- **Latency by Model** (box plot or bar with p50/p95/p99 whiskers).
- **Token Efficiency** (prompt vs. completion vs. cached vs. reasoning, stacked bar per model).

Each panel is independently:
- Sortable (by cost, count, name).
- Exportable (CSV, image).
- Clickable (clicking a bar filters the entire dashboard to that dimension value).

Users can rearrange panels via drag-and-drop (layout persisted in localStorage).

### 5.8 Log Viewer

A full-featured data table at the bottom of the dashboard (collapsible to save space):

**Columns** (all toggleable):
- Timestamp (local timezone)
- Model (short name)
- Provider
- API Key (label)
- Tokens (prompt / completion / total)
- Cached Tokens
- Reasoning Tokens
- Cost ($)
- Latency (ms)
- Tokens/sec (derived: tokens_completion / generation_time)
- Streamed (yes/no)
- Finish Reason
- Origin
- Media Count

**Features**:
- **Full-text search** across all visible columns.
- **Column sorting** (click header to sort, shift-click for multi-column sort).
- **Column visibility toggle** (dropdown to show/hide columns).
- **Row expansion** -- click a row to see full generation detail (all fields, raw trace metadata).
- **Pagination** with configurable page size (25, 50, 100, 250).
- **Export** -- CSV or JSON of the current filtered/sorted view (not just the visible page, the full query result).
- **Virtual scrolling** for smooth performance with large datasets.

### 5.9 Export System

Every exportable surface has a consistent export button/menu:

- **CSV**: Raw data underlying the current view. Column headers match the display names.
- **PNG**: Rasterized screenshot of the chart/panel at 2x resolution.
- **SVG**: Vector export of the chart (clean, scalable, editable in Illustrator/Figma).
- **JPG**: Compressed raster for quick sharing.

For chart image export, the approach is:
- **Client-side**: Use html2canvas or a similar library to capture the chart DOM as an image. Recharts renders to SVG, so SVG export is native.
- **CSV**: The frontend requests the same API endpoint it used to render the chart, but adds `format=csv` to get raw data.

### 5.10 Real-Time Behavior

When the WebSocket connection is active:

- New generations appear at the top of the log viewer (with a subtle highlight animation).
- KPI cards increment live (count ticks up, cost accumulates).
- The main chart's "current" bucket updates in place (no full re-fetch).
- A small "live" indicator (pulsing green dot) appears in the header.
- If the WebSocket disconnects, a yellow banner appears: "Live updates paused. Reconnecting..." with automatic exponential backoff retry.

Users can pause live updates (useful when analyzing historical data without the view shifting).

---

## 6. Networking: Exposing the Webhook Endpoint

OpenRouter's Broadcast system needs to reach RouterView's `/v1/traces` endpoint over the public internet. Since RouterView runs locally, we need a tunnel.

### 6.1 Recommended: Cloudflare Tunnel

Cloudflare Tunnel (free tier) is the recommended approach:

1. Install `cloudflared` on the host machine.
2. Run `cloudflared tunnel --url http://localhost:8100` to get a public URL.
3. Enter that URL + `/v1/traces` as the Webhook destination in OpenRouter Settings > Broadcast.
4. The tunnel persists as long as `cloudflared` is running. Can be set up as a system service for always-on operation.

### 6.2 Alternative: ngrok

`ngrok http 8100` provides a similar public URL. Free tier has limitations (URL changes on restart, rate limits).

### 6.3 Alternative: Cloud Relay

For always-on ingestion without a local tunnel:

- Deploy a tiny receiver (e.g., on fly.io free tier or a $5 VPS) that receives OTLP traces and forwards to RouterView via a persistent WebSocket or stores-and-forwards.
- RouterView pulls from the relay on startup and maintains a live connection.

### 6.4 Setup Wizard

RouterView should include a first-run setup wizard that:

1. Asks for the OpenRouter provisioning API key.
2. Detects if `cloudflared` is installed; if so, offers to start a tunnel automatically.
3. Displays the webhook URL to configure in OpenRouter.
4. Runs a test connection flow (listens for the `X-Test-Connection` probe).
5. Offers to do an initial backfill from the Activity API.

The wizard runs automatically on first launch (when no settings exist in the database). On completion, it writes a `setup_complete` flag to the `settings` table so it doesn't re-trigger.

### 6.5 Reconfiguration

The full setup wizard is re-accessible at any time from Settings > Reconfigure (or via URL: `/#/setup`). This allows:

- **Changing the provisioning API key** (e.g., if it was rotated on OpenRouter).
- **Updating the tunnel URL** -- critical when using Quick Tunnels, since the URL changes on every `cloudflared` restart. The reconfigure flow shows the current tunnel URL, lets you paste the new one, and provides a one-click "Copy webhook URL" button so you can paste it into OpenRouter's Broadcast settings.
- **Re-running the connection test** to verify the full pipeline is working (RouterView <-- tunnel <-- OpenRouter).
- **Triggering a backfill** from the Activity API to fill any gaps from downtime.
- **Resetting broadcast** -- a "Disconnect" option that clears the local configuration (does not touch OpenRouter's side; the user must remove the webhook destination there manually).

The reconfigure page also shows a **connection status panel** with:

- Last trace received (timestamp and how long ago).
- Tunnel URL currently configured.
- Whether the OTLP endpoint is reachable from localhost (self-test via loopback).
- Total traces received today / this session.
- Any recent ingestion errors from the `ingestion_log` table.

This gives a single place to diagnose "why am I not getting data?" without digging through logs.

---

## 7. Implementation Plan

### Phase 1: Foundation

**Goal**: Data flows from OpenRouter to SQLite and displays in a basic dashboard.

1. **Self-bootstrapping script** (`routerview`): Following editdb pattern. Dependencies: `fastapi`, `uvicorn`, `aiosqlite`.
2. **SQLite schema initialization**: Create tables and indexes on first run.
3. **OTLP receiver endpoint** (`/v1/traces`): Parse OTLP/HTTP+JSON payloads, extract generation data, insert into SQLite. Include payload capture/debug mode.
4. **Basic REST API**: `/api/summary`, `/api/timeseries`, `/api/generations`, `/api/dimensions`.
5. **Embedded React SPA**: Header, time range picker, KPI cards, one chart (cost over time as stacked area), and a basic log table.
6. **WebSocket**: Push new-generation events to the frontend.

### Phase 2: Full Dashboard

**Goal**: Feature-complete dashboard with all panels and interactions.

7. **Breakdown panels**: Cost by model, cost by key, requests by provider, latency analysis.
8. **Filter bar**: Multi-select filters for all dimensions with URL state sync.
9. **Chart interactions**: Click-drag zoom, legend toggle, chart type switching, Y-axis metric selector.
10. **Log viewer enhancements**: Column toggle, search, row expansion, sort, pagination.
11. **Comparison mode**: "Compare to previous period" overlay on charts.
12. **Daily summary materialization**: Background job to compute/refresh `daily_summaries` table.

### Phase 3: Export and Polish

**Goal**: Production-quality UX with full export capabilities.

13. **CSV export**: All views (summary, timeseries, breakdown, log).
14. **Image export**: PNG/SVG/JPG for all charts via html2canvas + native SVG export.
15. **Settings page**: API key management, tunnel config, theme toggle, data retention/purge.
16. **Setup wizard**: First-run experience for configuring the broadcast webhook.
17. **Fallback ingestion**: CSV import and API polling as secondary data sources.
18. **Dark/light theme**: Full theme support with localStorage persistence.

### Phase 4: Advanced Analytics

**Goal**: Power-user features for deep cost analysis.

19. **Heatmap view**: Hour x Day-of-Week usage intensity.
20. **Cost projection**: Based on current trends, project cost for the remainder of the period.
21. **Anomaly highlighting**: Flag requests with unusually high cost, latency, or token count.
22. **Panel drag-and-drop**: Rearrangeable dashboard layout.
23. **Custom dashboards**: Save multiple filter/layout configurations as named views.
24. **Keyboard shortcuts**: Time range navigation (left/right arrows), quick filter (/ to focus search).

---

## 8. Open Questions and Risks

### 8.1 OTLP Payload Schema: Adaptive Parsing

The exact span attributes in OpenRouter's OTLP traces are not fully documented publicly, and even if they were, OpenRouter could change them at any time. The parser must therefore be **adaptive by design**, not dependent on a locked schema.

Implementation approach:
- **Capture everything**: On receipt, store the full raw OTLP span attributes as a JSON blob in `trace_metadata`. This is the source of truth and is never discarded.
- **Best-effort extraction**: An external mapping file maps known OTLP attribute names to `generations` table columns. This mapping is applied at parse time. Unknown attributes are silently preserved in `trace_metadata`.
- **External mapping file**: The mapping lives at `~/.routerview/attribute_mapping.json`, NOT in the code. This means updating the mapping never requires editing, redeploying, or even restarting the script. See Section 10.9 for the file format and hot-reload behavior.
- **Debug mode for discovery**: On first run, use `--debug` to capture raw OTLP payloads to disk. Inspect a few to confirm/adjust the mapping. Make a few OpenRouter API requests and examine `~/.routerview/traces/` to see the actual attribute names. Then edit `~/.routerview/attribute_mapping.json` to match.
- **No code editing ever**: The script ships with a built-in default mapping (compiled in). On first run, it writes this default to `~/.routerview/attribute_mapping.json` if the file doesn't exist. From that point on, the external file takes precedence. The user edits a JSON file, not Python code.

### 8.2 Tunnel Reliability

Cloudflare Tunnel is generally reliable but adds a dependency. Mitigations:
- RouterView should detect when no new data has arrived and show a warning.
- The API polling fallback ensures no data is permanently lost (within the 30-day API window).
- Reconciliation: on startup, backfill any gaps from the Activity API.

### 8.3 SQLite Performance at Scale

For a single user or small team, SQLite should handle millions of rows comfortably. The `daily_summaries` materialized table offloads heavy aggregation queries. If performance becomes an issue:
- Add write-ahead logging (WAL mode) for concurrent read/write.
- Consider DuckDB as a drop-in replacement for analytical queries if needed.

### 8.4 Chart Image Export Quality

html2canvas has known limitations with some CSS features. If quality is insufficient:
- Use Recharts' built-in SVG rendering and convert to raster via `canvas.toBlob()`.
- For server-side rendering, use `playwright` or `cairosvg` to render SVGs to PNG.

---

## 9. File Structure

```
routerview/
  routerview              # Main executable (self-bootstrapping Python script)
  README.md
  docs/
    DESIGN.md             # This document
    SETUP_GUIDE.md        # Step-by-step setup: RouterView + tunnel + OpenRouter Broadcast
```

The single `routerview` file contains:
- Bootstrap/venv logic (top of file, runs before any third-party imports)
- FastAPI application with all routes
- OTLP parser
- SQLite data access layer
- Embedded HTML/React SPA as a Python string template
- WebSocket manager

This follows the editdb single-file architecture. The React SPA, all CSS, and all JavaScript are embedded in a Python string that is served from `GET /`.

---

## 10. Technical Specifications

### 10.1 CLI Entrypoint and Startup

The `routerview` script is a self-bootstrapping Python executable:

```
#!/usr/bin/env python3
"""RouterView -- OpenRouter Analytics Dashboard"""

VENV_DIR = os.path.expanduser("~/.routerview_venv")
DEPENDENCIES = ["fastapi", "uvicorn", "aiosqlite"]
DB_DEFAULT = os.path.expanduser("~/.routerview/routerview.db")
```

**CLI interface:**

```
Usage: routerview [OPTIONS]

Options:
  -p, --port PORT      Preferred port for the web server (default: 8100).
                       If the port is in use, auto-increments until an open port is found.
  --db PATH            Path to SQLite database (default: ~/.routerview/routerview.db)
  --debug              Enable debug logging and OTLP payload capture to ~/.routerview/traces/
  --host HOST          Bind address (default: 127.0.0.1)
  -h, --help           Show this help message
```

**Port auto-detection**: On startup, the server attempts to bind to the requested port (default 8100). If it fails with `EADDRINUSE`, it increments by 1 and retries, up to 20 attempts. The actual bound port is printed to stdout and stored in `~/.routerview/last_port` so other tools (e.g., a tunnel script) can discover it.

**Startup sequence:**

1. Bootstrap: check for venv, create if missing, install dependencies, re-exec if needed.
2. Parse CLI args.
3. Create `~/.routerview/` directory if it doesn't exist.
4. Initialize SQLite database (create tables, indexes, enable WAL mode).
5. Find an open port (starting from `--port` value, auto-incrementing if occupied).
6. Start FastAPI application via uvicorn on the discovered port.
7. Write port to `~/.routerview/last_port`.
8. Print: `RouterView running at http://127.0.0.1:{port}`
9. If `--debug`, also print: `OTLP payload capture enabled: ~/.routerview/traces/`

### 10.2 Timezone Handling

**Core principle: UTC in, UTC stored, UTC out. Local timezone is a display-layer concern only.**

This means the database is always consistent and timezone-agnostic. If you travel from Chicago to Tokyo, the data doesn't shift or become ambiguous -- only the rendering changes.

**Storage**: All timestamps in SQLite are stored in UTC (ISO 8601 with `Z` suffix). No exceptions. Incoming OTLP traces use nanosecond Unix timestamps (inherently UTC). The Activity API returns UTC. CSV imports are normalized to UTC on ingest.

**Derived date columns**: `created_date` and `created_hour` are computed at ingestion time in UTC. These exist solely for fast indexing and aggregation queries, not for display.

**API responses**: All timestamps returned by the backend are UTC. The backend never converts to local time.

**Frontend rendering**: The browser determines the user's local timezone via `Intl.DateTimeFormat().resolvedOptions().timeZone` and converts UTC timestamps to local time at render time. This means the same dashboard, opened from two different timezones, shows the same data but with locally correct timestamps.

**Calendar alignment for queries**: The frontend sends the user's timezone as a `tz` query parameter on all API requests. The backend uses this **only** to compute UTC boundaries for calendar-aligned ranges. For example, `range=this_week&tz=America/Chicago`:

1. Compute "this week" boundaries (Monday 00:00:00 to Sunday 23:59:59) in `America/Chicago`.
2. Convert those boundaries to UTC (Monday 06:00:00Z to Monday 05:59:59Z).
3. Query SQLite using the UTC boundaries against `created_at`.
4. Return results with UTC timestamps. The frontend converts for display.

**Bucket alignment**: Same principle. `bucket=day&tz=America/Chicago` groups by midnight-to-midnight Central Time, but the grouping math happens by converting each bucket boundary to UTC, not by storing local times.

**Dependency**: The `zoneinfo` module (stdlib in Python 3.9+) handles timezone conversions. No extra dependency needed.

**Travel scenario**: If you set up RouterView in Chicago (UTC-6) and fly to Tokyo (UTC+9), the dashboard auto-adjusts because the browser reports the new timezone. "Today" now means today in Tokyo. Historical data is unchanged -- a request that happened at 2pm Chicago time still shows as 2pm Chicago time if you manually select that timezone, or as 5am Tokyo time in local rendering.

### 10.3 WebSocket Message Format

The WebSocket at `/ws` sends JSON messages. Each message has a `type` field:

**New generation event:**

```json
{
  "type": "generation",
  "data": {
    "id": "gen-abc123",
    "created_at": "2026-03-06T14:32:01.000Z",
    "model_short": "claude-sonnet-4",
    "provider_name": "Anthropic",
    "tokens_prompt": 1200,
    "tokens_completion": 3321,
    "tokens_total": 4521,
    "cost_usd": 0.042,
    "generation_time_ms": 1800,
    "finish_reason": "stop",
    "streamed": true,
    "api_key_label": "prod-key",
    "origin": "https://myapp.com"
  }
}
```

**Connection status:**

```json
{
  "type": "status",
  "data": {
    "connected_clients": 2,
    "last_generation_at": "2026-03-06T14:32:01.000Z",
    "total_generations_today": 847,
    "db_size_mb": 124.5
  }
}
```

**Heartbeat** (sent every 30 seconds to keep the connection alive):

```json
{
  "type": "heartbeat",
  "data": {
    "server_time": "2026-03-06T14:32:30.000Z"
  }
}
```

The frontend uses `type` to route messages to the appropriate handler: `generation` events update KPI cards, append to the log viewer, and update the current chart bucket; `status` events update the header indicators.

### 10.4 Daily Summary Materialization

The `daily_summaries` table is rebuilt incrementally via three mechanisms:

**On each generation insert** (real-time): After inserting a new generation into the `generations` table, upsert the corresponding `daily_summaries` row. This is a single SQL `INSERT ... ON CONFLICT DO UPDATE` that increments counts, sums tokens/costs, and recomputes averages. Percentile values (p50/p95/p99) are NOT updated in real-time (too expensive per-insert).

**Background refresh** (runs every 15 minutes): A background asyncio task recomputes `daily_summaries` for the current day and previous day from the full `generations` data. This corrects any drift from the incremental upserts and computes percentile values (p50/p95/p99). The refresh targets only the last 2 days, not the full history. 15 minutes keeps percentiles reasonably fresh without unnecessary load.

**Manual refresh**: Two options:

- **Refresh recent** via `POST /api/admin/refresh-summaries` -- recomputes summaries for the current day and previous day, same as the background task but on demand. Fast (seconds). Useful if you want up-to-the-moment percentiles without waiting for the next background cycle. A "Refresh Stats" button in the Settings page triggers this.
- **Full rebuild** via `POST /api/admin/rebuild-summaries` -- drops and recreates all `daily_summaries` rows from the full `generations` table. Slower (depends on total data volume, but typically under a minute for hundreds of thousands of rows). Useful after a bulk import, schema migration, or if summaries look wrong. Protected behind a `confirm=true` parameter to prevent accidental invocation.

### 10.5 OTLP Payload Capture Mode

When `--debug` is passed, every OTLP payload received at `/v1/traces` is:

1. Written verbatim to `~/.routerview/traces/{timestamp}_{generation_id}.json`.
2. Also parsed and inserted normally into SQLite.

This serves two purposes:

- **Schema discovery**: On first setup with OpenRouter Broadcast, examine the raw payloads to verify/update the attribute mapping in Section 3.2.
- **Debugging**: If parsing fails or data looks wrong, the raw payloads are preserved for diagnosis.

Files in the traces directory are auto-purged after 7 days to prevent unbounded disk usage.

### 10.6 Error Handling for OTLP Ingestion

When the OTLP parser encounters issues:

- **Malformed JSON**: Return HTTP 400. Log the error. Do not crash.
- **Missing required fields** (e.g., no generation ID): Log a warning with the span data, skip that span, continue processing other spans in the batch. Return HTTP 200 (partial success).
- **Duplicate generation ID**: Upsert (update existing row). This is normal behavior, not an error.
- **Unknown span attributes**: Store them in the `trace_metadata` JSON blob. Never discard data.
- **Database write failure**: Return HTTP 500. Log the full error. The `ingestion_log` table records the failure.

### 10.7 SQLite Configuration

On database initialization:

```sql
PRAGMA journal_mode = WAL;          -- Write-ahead logging for concurrent reads during writes
PRAGMA synchronous = NORMAL;        -- Good durability without excessive fsync
PRAGMA cache_size = -64000;         -- 64MB page cache
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;         -- 5s wait on lock contention
```

WAL mode is critical because the OTLP ingestion writes frequently while the dashboard reads concurrently.

### 10.8 Color Palette and Theming

**Dark theme** (default):

- Background: `#0f172a` (slate-900)
- Surface: `#1e293b` (slate-800)
- Card: `#334155` (slate-700)
- Text primary: `#f1f5f9` (slate-100)
- Text secondary: `#94a3b8` (slate-400)
- Accent: `#3b82f6` (blue-500)
- Success: `#22c55e` (green-500)
- Warning: `#f59e0b` (amber-500)
- Error: `#ef4444` (red-500)

**Chart colors** (12-color categorical palette, high contrast on dark background):

```
#3b82f6  (blue)
#8b5cf6  (violet)
#ec4899  (pink)
#f59e0b  (amber)
#22c55e  (green)
#06b6d4  (cyan)
#f97316  (orange)
#a855f7  (purple)
#14b8a6  (teal)
#ef4444  (red)
#84cc16  (lime)
#64748b  (slate)
```

Each model is assigned a consistent color (hash of model name to palette index) so the same model always appears in the same color across all charts.

**Light theme**: Inverts the surface/background values. Text becomes slate-800/slate-600. Chart colors remain the same (they work on both backgrounds).

Theme preference is stored in `localStorage` and synced to the `settings` table for persistence across devices.

### 10.9 External Attribute Mapping

The OTLP-to-database column mapping is stored as an external JSON file, not in code. This means:
- No Python editing to adapt to schema changes.
- No redeployment. The script can live in `~/Library/Scripts/` or `/usr/local/bin/` as a symlink and never be touched.
- Changes can be picked up without restart (hot-reload on next trace).

**File location**: `~/.routerview/attribute_mapping.json`

**Bootstrap behavior**:
1. The script contains a built-in default mapping (hardcoded Python dict).
2. On first run, if `~/.routerview/attribute_mapping.json` doesn't exist, the script writes the default mapping to that file.
3. On every subsequent run (and on every incoming OTLP trace), the script reads the external file. The external file always takes precedence over the built-in default.
4. If the external file is deleted, the script falls back to the built-in default and re-creates the file.

**Hot-reload**: The mapping file is re-read from disk on each incoming OTLP batch (not cached in memory permanently). This means you can edit the file while RouterView is running and the next trace will use the updated mapping. The file is small (< 2KB), so the read overhead is negligible.

**File format**:

```json
{
  "_comment": "Maps OTLP span attribute names to RouterView database columns.",
  "_comment2": "Edit this file to adapt to OpenRouter schema changes. No code editing or restart needed.",
  "_updated": "2026-03-06T14:00:00Z",

  "id": {
    "attribute": "gen_ai.generation.id",
    "fallbacks": ["openrouter.generation_id", "generation_id"],
    "description": "Unique generation identifier"
  },
  "model": {
    "attribute": "gen_ai.request.model",
    "fallbacks": ["gen_ai.response.model", "llm.request.model"],
    "description": "Full model identifier (e.g., anthropic/claude-sonnet-4-20250514)"
  },
  "provider_name": {
    "attribute": "gen_ai.system",
    "fallbacks": ["llm.provider", "openrouter.provider_name"],
    "description": "Provider name (e.g., Anthropic, Google)"
  },
  "tokens_prompt": {
    "attribute": "gen_ai.usage.prompt_tokens",
    "fallbacks": ["gen_ai.usage.input_tokens", "llm.usage.prompt_tokens"],
    "type": "integer",
    "description": "Number of prompt tokens"
  },
  "tokens_completion": {
    "attribute": "gen_ai.usage.completion_tokens",
    "fallbacks": ["gen_ai.usage.output_tokens", "llm.usage.completion_tokens"],
    "type": "integer",
    "description": "Number of completion tokens"
  },
  "native_tokens_prompt": {
    "attribute": "gen_ai.usage.native_prompt_tokens",
    "fallbacks": ["openrouter.native_tokens_prompt"],
    "type": "integer",
    "description": "Native (model-specific) prompt token count"
  },
  "native_tokens_completion": {
    "attribute": "gen_ai.usage.native_completion_tokens",
    "fallbacks": ["openrouter.native_tokens_completion"],
    "type": "integer",
    "description": "Native completion token count"
  },
  "native_tokens_reasoning": {
    "attribute": "gen_ai.usage.reasoning_tokens",
    "fallbacks": ["openrouter.native_tokens_reasoning"],
    "type": "integer",
    "description": "Reasoning/thinking tokens"
  },
  "native_tokens_cached": {
    "attribute": "gen_ai.usage.cached_tokens",
    "fallbacks": ["openrouter.native_tokens_cached"],
    "type": "integer",
    "description": "Cached prompt tokens"
  },
  "cost_usd": {
    "attribute": "openrouter.usage.total_cost",
    "fallbacks": ["gen_ai.usage.cost", "llm.usage.total_cost"],
    "type": "float",
    "description": "Total cost in USD"
  },
  "generation_time_ms": {
    "attribute": "openrouter.generation_time",
    "fallbacks": ["gen_ai.latency"],
    "type": "integer",
    "description": "Generation time in milliseconds"
  },
  "finish_reason": {
    "attribute": "gen_ai.response.finish_reasons",
    "fallbacks": ["gen_ai.completion.finish_reason", "llm.response.stop_reason"],
    "description": "Why the generation stopped (stop, length, tool_calls, etc.)"
  },
  "streamed": {
    "attribute": "gen_ai.request.streaming",
    "fallbacks": ["openrouter.streamed"],
    "type": "boolean",
    "description": "Whether the response was streamed"
  },
  "origin": {
    "attribute": "openrouter.origin",
    "fallbacks": ["http.url", "url.full"],
    "description": "Origin URL of the request"
  },
  "app_id": {
    "attribute": "openrouter.app_id",
    "fallbacks": [],
    "description": "OpenRouter application ID"
  },
  "api_key_id": {
    "attribute": "openrouter.api_key_id",
    "fallbacks": ["openrouter.key_id"],
    "description": "API key identifier (not the secret)"
  },
  "cancelled": {
    "attribute": "openrouter.cancelled",
    "fallbacks": [],
    "type": "boolean",
    "description": "Whether the generation was cancelled"
  }
}
```

**Parsing logic**:

For each database column, the parser:
1. Looks for `attribute` in the span attributes.
2. If not found, tries each name in `fallbacks` in order.
3. If still not found, the column gets its default value (0 for integers, null for strings).
4. If `type` is specified, the value is cast accordingly.
5. Any span attributes NOT matched by any mapping entry are collected into the `trace_metadata` JSON blob.

The `fallbacks` array is the key to resilience. When OpenRouter renames an attribute, you add the new name as `attribute` and move the old name into `fallbacks` (or vice versa). Both old and new traces parse correctly.

**Validation**: On startup and on each reload, the parser validates the JSON structure (required keys exist, types are valid). If the file is malformed, it logs a warning and falls back to the built-in default until the file is fixed.

### 10.10 Portable Deployment

All runtime state lives under `~/.routerview/`:

```
~/.routerview/
  routerview.db              # SQLite database
  attribute_mapping.json     # OTLP attribute mapping (Section 10.9)
  last_port                  # Last bound port number
  traces/                    # Raw OTLP payloads (debug mode only)
```

The venv lives at `~/.routerview_venv/`.

The script itself (`routerview`) is fully self-contained and path-independent. It can be:

- Symlinked from anywhere: `ln -s /path/to/utilities/routerview/routerview ~/Library/Scripts/routerview`
- Copied to PATH: `cp routerview /usr/local/bin/`
- Run from any directory: `~/Library/Scripts/routerview`

No matter where or how it's invoked, it reads config from `~/.routerview/` and uses the venv at `~/.routerview_venv/`. The script never looks at its own filesystem location for config or data.
