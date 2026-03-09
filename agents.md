# AGENTS.md

## Scope
This repository is a personal utilities monorepo. Each top-level folder is an independent project with its own runtime, dependencies, and workflow.

## Core Rules
- Treat each top-level directory as a standalone project.
- Read that project's `README.md` before editing code.
- Keep changes scoped; do not refactor across unrelated projects unless explicitly asked.
- Many paths contain spaces (for example `Calculation tools`, `abacus usage`, `moneydance backup rotation`): always quote paths in shell commands.

## Documentation Discovery and Context
- **Follow documentation chains**: If a README references other docs (design docs, API specs, etc.), read those before making changes.
- **Check sibling directories**: Understand parent context and check for relevant documentation in sibling directories that might interact with your changes.
- **Document discovery**: Use `rg --files` to find files like `DESIGN.md`, `ARCHITECTURE.md`, `API.md`, or `docs/` folders.

## Robustness — Project-Specific Addition
The global CLAUDE.md defines base robustness and error handling rules. For interactive tools in this repo, gracefully handle errors and allow recovery when possible.

## Approach Before Effort

When a task is large, unfamiliar, or high-impact — or when an approach requires repeated tuning, workarounds, or accumulated rules to produce acceptable results — stop before investing further.

- Present 2-3 alternative approaches with tradeoffs before committing.
- Prefer the simplest approach that addresses the actual need.
- If an approach accumulates more than 2-3 corrective rules/workarounds and still produces inconsistent results, treat that as evidence the approach is wrong, not under-tuned.
- Do not optimize within an architecture you haven't validated. Validate the architecture first with a cheap probe, then optimize.

## Quality and Consistency
When changing existing code, maintain and extend existing frameworks:

- **Extend existing patterns**: If the project uses logging, testing, error handling, or input validation, extend those patterns to cover your changes.
- **Run validation**: After writing code, run the relevant commands from the Validation Matrix.
- **Match style**: Follow existing code style, naming conventions, and architectural patterns.
- **Complete implementations**: Avoid leaving TODOs without user approval.

### Regression Prevention
Before finalizing changes, verify you haven't:
- Removed or disabled existing logging or tests
- Bypassed existing validation or error handling
- Broken existing functionality in adjacent code

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

## Preferred Patterns for New Projects

### Self-Bootstrapping (Python/CLI projects)
When creating or updating a Python tool that a user runs directly, use the **self-bootstrapping pattern** from `editdb`. The script should work with zero manual setup — no separate install step, no README prerequisites beyond "run the command."

How it works:
1. The main script contains a `bootstrap()` function that runs before any third-party imports.
2. It checks whether dependencies are already importable. If so, it continues normally.
3. If imports fail, it creates a private venv (e.g. `~/.toolname_venv`), installs dependencies via pip, then re-executes itself with `os.execv()` using the venv's Python.
4. On subsequent runs the venv already exists, so startup is instant.

Key design rules:
- Use a user-home dot-directory for the venv (e.g. `~/.editdb_venv`) so it survives working-directory changes.
- Print brief progress messages during first-time setup.
- Single entry point — no separate `setup.sh`. Avoids PEP 668 issues on macOS/Homebrew.

When this does **not** apply:
- Single-file HTML/JS apps (no Python, no dependencies to manage).
- Projects that already use Docker as their delivery mechanism.
- Libraries or packages meant for `pip install` distribution.

### UI: Embedded React SPA (instead of Streamlit)
When a project needs a local web UI, prefer the **embedded single-file React SPA** pattern from `editdb` over Streamlit for responsiveness, layout control, and fewer dependencies.

Stack (all loaded via CDN — no `npm install`, no `node_modules`): React 18, ReactDOM 18, Babel Standalone, Tailwind CSS, Lucide Icons (all UMD/CDN from unpkg).

Architecture:
- Python backend (FastAPI + uvicorn) serves a single HTML template via `GET /`. All React/JSX, CSS, and Tailwind config are embedded in that HTML string.
- Frontend communicates with backend via `fetch()` to `/api/*` JSON endpoints.
- State via React `useState`/`useEffect` hooks. Dark mode via Tailwind `darkMode: 'class'` with localStorage. `ErrorBoundary` wraps the app.

When this does **not** apply: quick prototypes where Streamlit's speed-to-first-render matters more, or when the user explicitly requests Streamlit.

### Port Selection (local server tools)
Never hardcode a single port. Always scan for a free port starting from the preferred default.

Pattern (Python, using only stdlib `socket`):
```python
def find_free_port(start_port, max_attempts=20):
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port found in range {start_port}–{start_port + max_attempts - 1}")
```

Rules:
- Call `find_free_port(args.port)` in `main()` before starting the server or browser thread.
- If the resolved port differs from the requested one, log a warning (e.g. `"Port 8100 is in use; using port 8101 instead."`).
- Pass the resolved port to both the server (`uvicorn.run`) and the browser-open thread so they stay in sync.
- The default port in `argparse` is just a preference, not a requirement.

## Execution Guidance for Agents
- Prefer `rg`/`rg --files` for discovery.
- Prefer minimal, targeted diffs over broad formatting sweeps.
- Update documentation when behavior, interfaces, or run commands change.
- If a change touches multiple projects, validate each project independently with the commands above.
- Pytest environment note (Homebrew macOS): `pytest` may be installed as a shell entrypoint even when `python3 -m pytest` fails in a specific interpreter. For test execution, prefer `pytest` first; if needed, also try `python3 -m pytest` as a secondary option.
