# Utilities Toolkit
Personal collection of automation scripts, data tooling, and Streamlit apps that back day‑to‑day workflows. Each directory contains an isolated project with its own virtual environment bootstrap (`setup.sh`) where needed.

## Projects At A Glance

- `apple-health-extract` – Parse Apple Health `export.xml` to build workout summaries, heart‑rate detail, and incidental exercise bout analytics.
- `Calculation tools` – Self-contained HTML calculators for one-off finance scenarios (lump sum, early loan payoff, MoneySense comparisons).
- `data_format_converter` – A dual-interface utility for analyzing and converting text data formats (JSON, XML, YAML, TOON) with LLM token count analysis.
- `etf_montecarlo` – Monte-Carlo dividend forecaster that boots Yahoo Finance history to estimate per-ticker and portfolio income quantiles.
- `hysa-excel` – Python script that generates an Excel model comparing HYSA vs CD ladders with dynamic rates pulled from `inputs.csv`.
- `llm_collector` - A tool for collecting LLM usage data from a browser extension, with a Python collector, a browser extension, and a Dockerized container.
- `md-autotax` – Streamlit + CLI tools that convert state/federal tax tables into QIF files for Quicken, powered by YAML rule definitions.
- `md-json` – Moneydance JSON export to CSV converter with account hierarchy resolution and split transaction handling.
- `mem_snapshots` – Small shell helpers that snapshot macOS memory stats on reboot for later comparison.
- `mls-tracker` – Streamlit playoff tracker and standalone ESPN standings fetcher for MLS teams with team-branded theming.
- `moneydance backup rotation` – Standalone shell script that prunes NAS-hosted Moneydance backups by retention day, with optional file and syslog logging.
- `pdf-split` – Zsh utility that slices large PDFs into size-limited chunks using `qpdf`.
- `reversible-skew` – Burrows-Wheeler/Move-to-Front experiment with reversible block-wise compression and passthrough heuristics.
- `tax2` – Full rules-driven tax engine with Streamlit UI, CLI table generation, and QIF export pipelines.
- `toggle_wifi` – Post-wake automation that briefly toggles Wi-Fi to recover network connectivity on macOS.
- `transcription` – Whisper-backed Streamlit console for bulk transcription with meticulous session/lifetime counters and batching helpers.
- `vid-compiler` – MoviePy-based sampler that stitches highlight reels and tail segments from long raw footage.
- `video-scenes` – Quick reference commands for Detectron-based `scenedetect` workflows.
- `webserver` - A development web server environment using Docker, with a Node.js application, a Python application, and an Nginx reverse proxy.

Each project folder now ships a detailed `README.md` with setup instructions, usage examples, and implementation notes.
