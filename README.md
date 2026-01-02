# Utilities Toolkit
Personal collection of automation scripts, data tooling, and Streamlit apps that back day‑to‑day workflows. Each directory contains an isolated project with its own virtual environment bootstrap (`setup.sh`) where needed.

## Projects At A Glance

- `anduril_steps` – A calculator and solver for configuring "Stepped Ramp" brightness levels (1-150) on Anduril 2 flashlights.
- `apple-health-extract` – Parse Apple Health `export.xml` to build workout summaries, heart‑rate detail, and incidental exercise bout analytics.
- `Calculation tools` – Self-contained HTML calculators for one-off finance scenarios (lump sum, early loan payoff, MoneySense comparisons).
- `data_format_converter` – A dual-interface utility for analyzing and converting text data formats (JSON, XML, YAML, TOON, TOML) with LLM token count analysis.
- `doc_linearizer` – Command-line tool that flattens HTML documentation into a single Markdown file, preserving TOC order, numbering, and assets.
- `etf_montecarlo` – Monte-Carlo dividend forecaster that boots Yahoo Finance history to estimate per-ticker and portfolio income quantiles.
- `hysa-excel` – Python script that generates an Excel model comparing HYSA vs CD ladders with dynamic rates pulled from `inputs.csv`.
- `llm_collector` - A tool for collecting LLM usage data from a browser extension, with a Python collector that automatically consolidates daily snapshots, a browser extension, and a Dockerized container.

- `md-autotax` – Streamlit + CLI tools that convert state/federal tax tables into QIF files for Quicken, powered by YAML rule definitions.
- `md-json` – Moneydance JSON export to CSV converter with account hierarchy resolution and split transaction handling.
- `media-dater` – CLI wrapper for `exiftool` that safely renames image and video files by their creation date with collision handling and dry-run support.
- `mem_snapshots` – Small shell helpers that snapshot macOS memory stats on reboot for later comparison.
- `mls-tracker` – Streamlit playoff tracker and standalone ESPN standings fetcher for MLS teams with team-branded theming.
- `moneydance backup rotation` – Standalone shell script that prunes NAS-hosted Moneydance backups by retention day, with optional file and syslog logging.
- `pdf-split` – Zsh utility that slices large PDFs into size-limited chunks using `qpdf`.
- `qif_div_converter` – CLI tool that filters Fidelity dividend CSVs and converts them into Moneydance-compatible QIF files using a JSON configuration for account and fund mapping.
- `reversible-skew` – Burrows-Wheeler/Move-to-Front experiment with reversible block-wise compression and passthrough heuristics.
- `tax2` – Full rules-driven tax engine with Streamlit UI, CLI table generation, and QIF export pipelines.
- `toggle_wifi` – Post-wake automation that briefly toggles Wi-Fi to recover network connectivity on macOS.
- `transcription` – Whisper-backed Streamlit console for bulk transcription with meticulous session/lifetime counters and batching helpers.
- `vid-compiler` – MoviePy-based sampler that stitches highlight reels and tail segments from long raw footage.
- `video-scenes` – Quick reference commands for Detectron-based `scenedetect` workflows.
- `web_games/gorilla` – Modern browser remake of the classic QBasic **Gorilla.BAS** artillery game with AI opponents and local multiplayer.
- `web_games/rps_screen` – A browser-based Rock Paper Scissors particle simulation with elastic collision physics, auto-restart "screensaver" mode, and customizable game rules.
- `webserver` - A versatile local web server with Docker Compose, featuring Nginx, a Python FastAPI backend, a Node.js Express backend, and a dynamic file browser with a built-in UI for managing reverse-proxy routes.

Each project folder now ships a detailed `README.md` with setup instructions, usage examples, and implementation notes.
