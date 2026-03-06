# Utilities Toolkit
Personal collection of automation scripts, data tooling, and local web apps that back day‑to‑day workflows. Each directory contains an isolated project with its own virtual environment bootstrap (`setup.sh`) or self-bootstrapping entry point where needed.

## Flagship Utilities

The most polished and feature-complete tools in the collection — each is a self-bootstrapping, zero-setup application with a professional-grade web UI.

### harscope
HAR file analyzer and sanitizer built for developers and security reviewers who need to understand, inspect, and safely share HTTP Archive captures. It renders a full waterfall timeline of network requests, lets you drill into individual request/response pairs with an interactive inspector, and runs value-first secret detection to flag leaked credentials or tokens. Sequence diagrams and dashboard summaries give you a high-level picture at a glance, while inline keyboard-driven redaction lets you surgically sanitize sensitive data before export. Output formats include cleaned HAR, CSV, Markdown, and self-contained HTML reports.

### jtree
Interactive JSON viewer and editor that renders any JSON document as a pannable, zoomable node-graph mind map. Instead of scrolling through collapsed trees in a text editor, you explore data spatially — clicking nodes to expand branches, dragging to reposition, and using a minimap for orientation in large documents. Full CRUD editing is built in: add, rename, delete, copy/paste nodes, reorder arrays, and undo/redo up to 50 operations. Search filters across keys, values, or both, and finished visualizations export to SVG, PNG, or JPEG for documentation or presentations.

### routerview
Self-hosted OpenRouter analytics dashboard that replaces the official Activity page with a dramatically superior experience. Ingests real-time OTLP traces via OpenRouter's Observability Broadcast, stores everything locally in SQLite with indefinite retention, and serves an SRE-grade React dashboard with KPI cards, timeseries charts, breakdown panels, a usage heatmap, and a full generation log viewer. Eight comparison modes (DoD, WoW, MoM, QoQ, YoY, and more) with calendar-aware prior period logic render as split stacked charts with shared Y-axis scale and linked crosshairs. A cumulative toggle lets you track running spend against prior periods to answer "are we on track this month?" at a glance. Multi-dimensional filtering, drag-and-drop panels, saved views, CSV/PNG/SVG/JPG export, and adaptive OTLP attribute mapping round out the feature set.

### editdb
Professional-grade, local web-based SQLite database manager that brings an Airtable-style editing experience to any `.db` file. Point it at a database from the command line and get a high-performance React data grid with sticky headers, inline editing, and paginated browsing. The schema designer handles column additions, type changes, and renames through automated migrations, while a built-in SQL console with query history covers ad-hoc exploration. Import and export support CSV and JSON, and the whole tool runs localhost-only with SQL injection protection baked in — no cloud, no accounts, no setup beyond running the script.

## Notable Utilities

Capable tools that solve specific problems well and see regular use.

### llm_proxy
Modular, stateless proxy that makes non-standard LLM provider APIs speak the OpenAI `/v1/chat/completions` protocol. Currently bridges T3.chat and can be extended to additional providers by dropping in a new adapter module. It handles streaming SSE translation, tool-calling format conversion, dynamic model discovery, and BYOK auto-retry — making it possible to point standard OpenAI-compatible clients (like opencode or jimmychat) at providers that don't natively support the protocol. Runs as a single Docker container with path-based routing and per-request credentials.

### tax2
Full rules-driven tax engine that computes federal and state income tax from YAML-defined bracket tables, deductions, and credits. It supports dynamic year selection, precomputed lookup tables for fast queries, consistency cross-checking between rules and tables, and QIF export for direct import into Quicken or Moneydance. The web UI offers multiple operational modes — rules compute, table lookup, cross-check, and QIF export — while a CLI mode handles batch table generation for all supported years.

### docpipe
Fully local document conversion pipeline that turns PDF, DOCX, PPTX, HTML, and XLSX files into clean Markdown and structured JSON suitable for LLM ingestion or archival. It handles the messy reality of real-world documents — extracting text, tables, speaker notes, and optionally page images — while falling back gracefully when optional tools like Pandoc or Poppler aren't installed. Like the flagship tools it self-bootstraps its own venv on first run, so there's nothing to install beyond running the script.

### mls-tracker
Live MLS playoff race dashboard that pulls standings from ESPN's public API and layers on clinch/elimination logic, configurable cutoff position analysis, and playoff scenario breakdowns. It shows worst-case and easiest-path projections, identifies which results a team needs from other matches, and dynamically sources team branding (colors and logos) so the display stays current. Built for the stretch run of the season when every match matters and the scenarios get complicated.

## Projects At A Glance

- `abacus usage` – Automates the extraction and processing of ChatLLM credit usage data from the Abacus.AI dashboard.
- `anduril_steps` – A calculator and solver for configuring "Stepped Ramp" brightness levels (1-150) on Anduril 2 flashlights.
- `apple-health-extract` – Parse Apple Health `export.xml` to build workout summaries, heart‑rate detail, and incidental exercise bout analytics.
- `Calculation tools` – Self-contained HTML calculators for one-off finance scenarios (lump sum, early loan payoff, MoneySense comparisons).
- `Claude_plugin_converter` – Utilities for converting Claude-style plugins (skills and commands) to other CLI formats, currently supporting Gemini CLI.
- `data_format_converter` – A dual-interface utility for analyzing and converting text data formats (JSON, XML, YAML, TOON, TOML) with LLM token count analysis.
- `dloc` – Daily Lines of Code utility that parses git history to report insertions, deletions, and net changes by date.
- `docker` – Grouped home for containerized utilities (see `docker/README.md`).
- `docker/actual-data` – Docker configuration and data for Actual Budget, a local-first personal finance application.
- `docker/excalidraw` – Docker Compose setup for a local Excalidraw whiteboard instance.
- `docker/llm_collector` - Tooling for collecting LLM usage data, including the browser extension, collector service, and Docker runtime.
- `docker/llm_proxy` - Modular OpenAI-compatible proxy that exposes non-standard LLM provider APIs (currently T3.chat) as standard `/v1/chat/completions` endpoints.
- `docker/mermaid` – Scripts to run a local instance of the Mermaid Live Editor using Docker.
- `docker/webserver` - Local Docker Compose web stack with Nginx, FastAPI, Express, and a configurable file browser/reverse proxy.
- `doc_linearizer` – Command-line tool that flattens multi-page HTML documentation sites into a single Markdown file, preserving TOC order, numbering, and assets.
- `docpipe` – Fully local document conversion pipeline. Converts PDF, DOCX, PPTX, HTML, and XLSX to canonical Markdown + JSON for model ingestion.
- `editdb` – Professional-grade, local web-based SQLite management utility with a high-performance React data grid and automated schema migrations.
- `etf_montecarlo` – Monte-Carlo dividend forecaster that boots Yahoo Finance history to estimate per-ticker and portfolio income quantiles.
- `harscope` – HAR file analyzer and sanitizer with waterfall timing, request inspection, secret detection, sequence diagrams, dashboard stats, and sanitized export.
- `hysa-excel` – Python script that generates an Excel model comparing HYSA vs CD ladders with dynamic rates pulled from `inputs.csv`.
- `jtree` – Interactive JSON viewer and editor that renders JSON as a pannable/zoomable node-graph mind map with full CRUD, copy/paste, array reordering, undo/redo, search, and SVG/PNG/JPEG export.
- `llm_proxy` – Modular OpenAI-compatible proxy that exposes non-standard LLM provider APIs (currently T3.chat) as standard `/v1/chat/completions` endpoints.
- `md-autotax` – Streamlit + CLI tools that convert state/federal tax tables into QIF files for Quicken, powered by YAML rule definitions.
- `md-json` – Moneydance JSON export to CSV converter with account hierarchy resolution and split transaction handling.
- `media-dater` – CLI wrapper for `exiftool` that safely renames image and video files by their creation date with collision handling and dry-run support.
- `mem_snapshots` – Small shell helpers that snapshot macOS memory stats on reboot for later comparison.
- `mls-tracker` – Self-bootstrapping FastAPI + React SPA playoff tracker for both MLS conferences, with dynamic ESPN-sourced team branding, configurable cutoff position, and clinch/elimination logic.
- `moneydance backup rotation` – Standalone shell script that prunes NAS-hosted Moneydance backups by retention day, with optional file and syslog logging.
- `pdf-split` – Zsh utility that slices large PDFs into size-limited chunks using `qpdf`.
- `prep_ledger` – Python CLI utility designed to clean and reformat Fidelity "Accounts History" CSV exports.
- `qif_div_converter` – CLI tool that filters Fidelity dividend CSVs and converts them into Moneydance-compatible QIF files using a JSON configuration for account and fund mapping.
- `routerview` – Self-hosted OpenRouter analytics dashboard with real-time OTLP ingestion, 8 comparison modes, cumulative cost tracking, split chart comparison, and full export. Replaces the official OpenRouter Activity page.
- `reversible-skew` – Burrows-Wheeler/Move-to-Front experiment with reversible block-wise compression and passthrough heuristics.
- `tax2` – Full rules-driven tax engine with FastAPI + React SPA UI, CLI table generation, and QIF export pipelines.
- `toggle_wifi` – Post-wake automation that briefly toggles Wi-Fi to recover network connectivity on macOS.
- `transcription` – Whisper-backed Streamlit console for bulk transcription with meticulous session/lifetime counters and batching helpers.
- `vid-compiler` – MoviePy-based sampler that stitches highlight reels and tail segments from long raw footage.
- `video-scenes` – Quick reference commands for Detectron-based `scenedetect` workflows.
- `web_games/gorilla` – Modern browser remake of the classic QBasic **Gorilla.BAS** artillery game with AI opponents and local multiplayer.
- `web_games/multibody_sim` – Browser-based N-body gravity sandbox/screensaver with user setup mode, collision merges, trails/leads, and JSON save/load.
- `web_games/rps_screen` – A browser-based Rock Paper Scissors particle simulation with elastic collision physics, auto-restart "screensaver" mode, and customizable game rules.

Each project folder now ships a detailed `README.md` with setup instructions, usage examples, and implementation notes.
