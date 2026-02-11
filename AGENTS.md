# AGENTS.md

## Scope
This repository is a personal utilities monorepo. Each top-level folder is an independent project with its own runtime, dependencies, and workflow.

## Core Rules
- Treat each top-level directory as a standalone project.
- Read that project's `README.md` before editing code.
- Keep changes scoped; do not refactor across unrelated projects unless explicitly asked.
- Many paths contain spaces (for example `Calculation tools`, `abacus usage`, `moneydance backup rotation`): always quote paths in shell commands.

## Repo Shape (High-Level)
- Python/CLI/Streamlit tools: `tax2`, `data_format_converter`, `transcription`, `mls-tracker`, `apple-health-extract`, `md-autotax`, `md-json`, `doc_linearizer`, `qif_div_converter`, `prep_ledger`, etc.
- Browser-first single-file apps: `web_games/gorilla`, `web_games/multibody_sim`, `web_games/rps_screen`, plus HTML calculators under `Calculation tools`.
- Docker stacks and services: `docker/actual-data`, `docker/excalidraw`, `docker/llm_collector`, `docker/mermaid`, `docker/webserver`.

## Validation Matrix
Run the smallest relevant check for the area you changed:

- `data_format_converter`:
  - `python3 -m pytest`
- `web_games/multibody_sim`:
  - `npm test` (Playwright; config launches local `http-server` on `127.0.0.1:4173`)
- `tax2`:
  - `python3 -m pytest` (currently minimal coverage)
  - If tax rules/table generation changed, also run `python3 cli.py generate-combined --year 2026` (or target year used by your change).
- Streamlit apps (`tax2`, `transcription`, `mls-tracker`, `md-autotax`):
  - smoke-run the app entrypoint after edits (`streamlit run ...` or project `run.sh`/`ui.sh`).
- Shell utilities (`pdf-split`, `media-dater`, `toggle_wifi`, etc.):
  - run `--help` and at least one safe/dry-run style command when available.

## Large/Vendored Directories
Avoid broad searches or edits in vendored/generated trees unless the task explicitly requires it:
- `tax2/.venv/`
- `data_format_converter/venv/`
- `docker/webserver/index/node_modules/`
- `docker/webserver/app_node/node_modules/`
- `**/__pycache__/`, `**/.pytest_cache/`

## Sensitive/Stateful Files
- Treat API keys and local state as sensitive. Do not expose secret values in diffs or logs.
- Pay special attention in `docker/llm_collector/` (`MY_API_KEY.txt`, compose/env config, extension config, state/snapshot files).
- Be careful editing runtime/state artifacts such as:
  - `transcription/session_backup.json`
  - `transcription/transcription_odometer.txt`
  - `docker/llm_collector/state.json`
  - `docker/llm_collector/snapshots/*`

## Project-Specific Notes
- `web_games/gorilla/index.html` and `web_games/multibody_sim/index.html` are intentionally single-file apps; preserve this architecture unless instructed otherwise.
- `web_games/multibody_sim/docs/` contains active implementation and cleanup notes; keep docs in sync when behavior changes.
- `docker/webserver/README.md` documents routing invariants; preserve static-first routing and `/files`/`/configure` behavior when touching proxy logic.

## Execution Guidance for Agents
- Prefer `rg`/`rg --files` for discovery.
- Prefer minimal, targeted diffs over broad formatting sweeps.
- Update documentation when behavior, interfaces, or run commands change.
- If a change touches multiple projects, validate each project independently with the commands above.
