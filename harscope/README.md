# harscope

HAR (HTTP Archive) file analyzer and sanitizer. Combines rich visualization with integrated secret detection and sanitized export in a single-file tool.

## Features

- **Waterfall View** - Paginated request timeline with stacked timing bars (blocked/DNS/connect/SSL/send/wait/receive), domain/status/type/search filtering, per-row security indicators (shield icons with red/amber severity coloring)
- **Inspector View** - Full request/response detail with headers, cookies, query params, body (JSON syntax-highlighted), timing breakdown, and WebSocket messages. Security findings are surfaced inline: red badges on Request/Response toggles and per sub-tab, flagged headers/cookies highlighted, body keys with findings shown in red with marked values
- **Security View** - Value-first secret detection across the entire HAR tree. Findings are consolidated per field (multiple detectors on the same value merge into one finding). Severity ratings, per-finding redact toggles, severity/category filtering
- **Sequence Diagram** - CSS-based sequence diagram with browser-to-server flows, domain filtering, detected patterns (OAuth, redirect chains, API groups), and response toggle
- **Dashboard** - Summary cards (requests, size, load time, error rate), status code/domain/content type bar charts, timing percentiles
- **Export** - Sanitized HAR (redacted secrets with full value replacement), CSV, Markdown report, HTML report with bulk redaction controls

## Usage

```bash
./harscope [file.har] [--port 8200]
```

### Examples

```bash
# Open a HAR file directly
./harscope capture.har

# Open on a custom port
./harscope capture.har --port 9000

# Launch without a file (use drag-and-drop or file picker in browser)
./harscope

# Multiple instances auto-select available ports starting from default
./harscope file1.har &
./harscope file2.har &
```

## Requirements

- Python 3.8+
- Internet connection on first run (downloads React, Tailwind, fonts via CDN)

## First-Time Setup

On first run, harscope automatically creates a private virtual environment at `~/.harscope_venv` and installs its dependencies (FastAPI, uvicorn, python-multipart). Subsequent runs start instantly.

## How to Capture a HAR File

1. Open Chrome DevTools (F12)
2. Go to the Network tab
3. Load/use the page you want to analyze
4. Right-click in the Network panel > "Save all as HAR with content"

## Security Scanner

The 2023 Okta breach demonstrated the danger of sharing unsanitized HAR files - attackers extracted session tokens from shared files. harscope automatically scans the entire HAR tree for secrets using a value-first approach:

### Detection Philosophy

Detection is **value-first, not key-first**. Key names boost confidence (lower thresholds) but never gate detection. Any long opaque string is evaluated regardless of its field name.

### 3-Tier Token Detection

| Tier | Condition | Severity |
|------|-----------|----------|
| 1 | Key name hints at secret + 32+ chars + 2+ char classes | Critical |
| 2 | Any key + 48+ chars + 2+ char classes | Warning |
| 3 | Any key + 80+ chars + 10+ unique chars | Warning |

### What It Catches

- **Critical**: Authorization headers, session cookies, JWT tokens, Bearer/Basic auth, API keys, sensitive URL parameters, opaque tokens in any field
- **Warning**: HTTP (non-HTTPS) requests, missing cookie security flags (httpOnly, secure), long opaque tokens without key hints
- **Info**: Private IP addresses

### Consolidation

Multiple detectors flagging the same field (e.g., JWT pattern + token heuristic on the same value) are consolidated into a single finding with merged descriptions and the highest severity.

### Redaction

Redaction replaces the **entire value** with `[REDACTED]` by parsing the body JSON, navigating to the target key, and re-serializing. Previously redacted values (`[REDACTED]`) are skipped on rescan.

Review findings in the Security tab, toggle redaction per-finding or in bulk, then export a sanitized HAR from the Export tab.

## Architecture

Single-file Python application with:
- Self-bootstrapping venv (`~/.harscope_venv`)
- FastAPI backend with ~20 REST endpoints
- Embedded React 18 SPA (CDN: React, Babel, Tailwind, Lucide Icons, Google Fonts)
- No build step, no npm, no node_modules
- Recursive whole-tree scanner with JSON body parsing, base64 decoding, and WebSocket message inspection

## Port

Default: 8200. Multiple instances auto-probe ports 8200-8219 to avoid conflicts.
