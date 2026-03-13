# Utilities Toolkit
Personal collection of automation scripts, data tooling, and local web apps that back day‑to‑day workflows. Each directory contains an isolated project with its own runtime model — increasingly a self-bootstrapping launcher backed by a dedicated home-directory runtime under `~/.projectname/` so copied or symlinked installs keep working without manual setup.

## Flagship Utilities

The most polished and feature-complete tools in the collection — each is a self-bootstrapping, zero-setup application with a professional-grade web UI.

### harscope
HAR file analyzer and sanitizer built for developers and security reviewers who need to understand, inspect, and safely share HTTP Archive captures. It renders a full waterfall timeline of network requests, lets you drill into individual request/response pairs with an interactive inspector, and runs value-first secret detection to flag leaked credentials or tokens. Sequence diagrams and dashboard summaries give you a high-level picture at a glance, while inline keyboard-driven redaction lets you surgically sanitize sensitive data before export. Output formats include cleaned HAR, CSV, Markdown, and self-contained HTML reports.

### jtree
Interactive JSON viewer and editor that renders any JSON document as a pannable, zoomable node-graph mind map. Instead of scrolling through collapsed trees in a text editor, you explore data spatially — clicking nodes to expand branches, dragging to reposition, and using a minimap for orientation in large documents. Full CRUD editing is built in: add, rename, delete, copy/paste nodes, reorder arrays, and undo/redo up to 50 operations. Search filters across keys, values, or both, and finished visualizations export to SVG, PNG, or JPEG for documentation or presentations.

### routerview
Self-hosted OpenRouter analytics dashboard that replaces the official Activity page with a dramatically superior experience. Ingests real-time OTLP traces via OpenRouter's Observability Broadcast, stores everything locally in SQLite with indefinite retention, and serves an SRE-grade React dashboard with KPI cards, timeseries charts, breakdown panels, a usage heatmap, and a full generation log viewer. Eight comparison modes (DoD, WoW, MoM, QoQ, YoY, and more) with calendar-aware prior period logic render as split stacked charts with shared Y-axis scale and linked crosshairs. A cumulative toggle lets you track running spend against prior periods to answer "are we on track this month?" at a glance. Multi-dimensional filtering, drag-and-drop panels, saved views, CSV/PNG/SVG/JPG export, and adaptive OTLP attribute mapping round out the feature set.

### cognitive_switchyard
Single-user, local-first task orchestration engine that coordinates parallel execution of arbitrary workloads through a multi-phase pipeline. Work items drop into an intake directory as markdown files, then flow through LLM-driven planning, dependency resolution, constraint-aware parallel dispatch to worker slots, verification, and bounded auto-fix — all visible in a real-time React dashboard. Runner packs make the engine workload-agnostic: the built-in `claude-code` pack turns it into a parallel coding agent orchestrator, but the same pipeline handles any CLI-driven workload. Sessions support git worktree isolation, idempotent crash recovery, streaming phase logs, and a three-trigger verification system (interval, task-driven, and mandatory final). The web UI provides setup, live monitoring with pipeline strip and worker cards, session history, and global settings management.

### git-multirepo-dashboard (Git Fleet)
Local multi-repo git dashboard built for monorepos and multi-project setups. Register a directory of repos and get a fleet overview with activity sparklines, branch staleness tracking, and full dependency health scanning across Python, Node, Go, Rust, Ruby, and PHP ecosystems. Dependency detection walks subdirectories up to three levels deep, so monorepos with scattered manifest files are fully covered — each dependency tracks exactly which sub-project it belongs to. A full scan aggregates commit history into daily stats, lists all branches with stale/active badges, and runs ecosystem-specific outdated and vulnerability checks. Real-time SSE progress streaming, a built-in directory browser for repo registration, and fleet-wide analytics (commit heatmaps, time allocation, cross-repo dependency overlap) round out the feature set.

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

### expense_dock
Local OneDrive expense intake console for accountants-and-spreadsheet workflows that still need proper file handling. It authenticates against personal Microsoft accounts via Graph, creates `YYYY/YYYY-MM` receipt folders on demand inside a shared OneDrive expense root, uploads receipts with normalized filenames, creates anonymous read-only share links, then downloads and rewrites the Excel tracker in-memory with a new expense row. A focused React workspace separates submission, setup, retry queue, and workbook lookup views, while a persistent status bar keeps auth/config health visible at all times.

### mls-tracker
Live MLS playoff race dashboard that pulls standings from ESPN's public API and layers on clinch/elimination logic, configurable cutoff position analysis, and playoff scenario breakdowns. It shows worst-case and easiest-path projections, identifies which results a team needs from other matches, and dynamically sources team branding (colors and logos) so the display stays current. Built for the stretch run of the season when every match matters and the scenarios get complicated.

## Projects At A Glance

- `abacus usage` – Automates the extraction and processing of ChatLLM credit usage data from the Abacus.AI dashboard.
- `anduril_steps` – A calculator and solver for configuring "Stepped Ramp" brightness levels (1-150) on Anduril 2 flashlights.
- `apple-health-extract` – Parse Apple Health `export.xml` to build workout summaries, heart‑rate detail, and incidental exercise bout analytics.
- `Calculation tools` – Self-contained HTML calculators for one-off finance scenarios (lump sum, early loan payoff, MoneySense comparisons).
- `Claude_plugin_converter` – Utilities for converting Claude-style plugins (skills and commands) to other CLI formats, currently supporting Gemini CLI.
- `coding` – Curated coding orchestration reference assets. Contains `task_orch/` (legacy task orchestration scaffold, deprecated in favor of Cognitive Switchyard) and `design_orch/` (design-document packetization and implementation loop extracted from Git Fleet).
- `cognitive_switchyard` – Local-first task orchestration engine with multi-phase pipeline (intake, planning, resolution, execution, verification, auto-fix), parallel worker dispatch, git worktree isolation, streaming phase logs, and a real-time React monitoring dashboard. Pluggable runner packs make it workload-agnostic.
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
- `expense_dock` – Self-bootstrapping FastAPI + React SPA for OneDrive-based expense intake. Uploads receipts into `YYYY/YYYY-MM`, creates anonymous receipt links, appends the Excel tracker via download-edit-upload, and keeps retry/status state in a local workspace.
- `editdb` – Professional-grade, local web-based SQLite management utility with a high-performance React data grid and automated schema migrations.
- `git-multirepo-dashboard` – Local multi-repo git dashboard with fleet overview, branch staleness tracking, monorepo-aware dependency scanning, and fleet-wide analytics.
- `etf_montecarlo` – Monte-Carlo dividend forecaster that boots Yahoo Finance history to estimate per-ticker and portfolio income quantiles.
- `fid_div_conv` – Combined Fidelity CSV workflow that replaces the retired `prep_ledger` and `qif_div_converter` tools. It writes a cleaned ledger CSV for Actual Budget and a dividend QIF for Moneydance in one run, with runtime config and bootstrap state stored under `~/.fid_div_conv/`.
- `harscope` – HAR file analyzer and sanitizer with waterfall timing, request inspection, secret detection, sequence diagrams, dashboard stats, and sanitized export.
- `hysa-excel` – Python script that generates an Excel model comparing HYSA vs CD ladders with dynamic rates pulled from `inputs.csv`.
- `jtree` – Interactive JSON viewer and editor that renders JSON as a pannable/zoomable node-graph mind map with full CRUD, copy/paste, array reordering, undo/redo, search, and SVG/PNG/JPEG export.
- `llm_proxy` – Modular OpenAI-compatible proxy that exposes non-standard LLM provider APIs (currently T3.chat) as standard `/v1/chat/completions` endpoints.
- `md-autotax` – Streamlit + CLI tools that convert state/federal tax tables into QIF files for Quicken, powered by YAML rule definitions.
- `md-json` – Moneydance JSON export to CSV converter with account hierarchy resolution and split transaction handling.
- `media-dater` – CLI wrapper for `exiftool` that safely renames image and video files by their creation date with collision handling and dry-run support.
- `mem_snapshots` – Small shell helpers that snapshot macOS memory stats on reboot for later comparison.
- `model_sentinel` – Local CLI tracker for authenticated LLM model lists across providers. Stores saved snapshots in SQLite, diffs adds/removes/metadata drift over time, supports history queries, and can run on a schedule via user-level `launchd`.
- `mls-tracker` – Self-bootstrapping FastAPI + React SPA playoff tracker for both MLS conferences, with dynamic ESPN-sourced team branding, configurable cutoff position, and clinch/elimination logic.
- `moneydance backup rotation` – Standalone shell script that prunes NAS-hosted Moneydance backups by retention day, with optional file and syslog logging.
- `pdf-split` – Zsh utility that slices large PDFs into size-limited chunks using `qpdf`.
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
- `worktree-helper` – Single-file, dependency-free Python utility for managing `git worktree` with a keyboard-driven TUI and full CLI flags. Supports create, delete, list, status, prune, open, cd, lock, unlock, move, repair, and doctor commands.

Each project folder now ships a detailed `README.md` with setup instructions, usage examples, and implementation notes.
