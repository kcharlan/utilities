# AGENTS.md

## Scope
This repository is a personal utilities monorepo. Each top-level folder is an independent project with its own runtime, dependencies, and workflow.

## Core Rules
- Treat each top-level directory as a standalone project.
- Read that project's `README.md` before editing code.
- Keep changes scoped; do not refactor across unrelated projects unless explicitly asked.
- Many paths contain spaces (for example `Calculation tools`, `abacus usage`, `moneydance backup rotation`): always quote paths in shell commands.

## Documentation Discovery and Context
When working in any project or subdirectory:
- **Read the local README first**: Always read the README.md in the specific directory where you're making changes, not just the repository root README.
- **Follow documentation chains**: If a README references other documentation files (design docs, API specs, architecture diagrams, etc.), read those as well before making changes.
- **Check parent and sibling directories**: When working in a subdirectory, understand the parent context and check for relevant documentation in sibling directories that might interact with your changes.
- **Document discovery**: Use `rg --files` to find documentation files like `DESIGN.md`, `ARCHITECTURE.md`, `API.md`, or `docs/` folders that provide critical context.

## Robustness and Error Handling
Robustness is a first-class requirement. All code must handle edge cases and exceptional conditions:

### Essential Checks
- **Boundary conditions**: Verify array/list accesses are within bounds; check for empty collections before iteration.
- **Arithmetic safety**: Guard against division by zero and floating-point precision issues.
- **Null/None safety**: Validate that objects and values exist before using them.
- **Input validation**: Validate external inputs (user input, file content, API responses) for basic type and format correctness.
- **Resource awareness**: Consider memory and disk space constraints, especially for batch file operations.

### Error Handling Patterns
- Use explicit error handling (try/except in Python, error returns in other languages) rather than assuming success.
- Provide clear error messages that help understand what went wrong.
- For interactive tools, gracefully handle errors and allow recovery when possible.
- For batch operations, decide whether to fail-fast or continue-with-errors based on the use case.

## Quality Gates and Code Review
Quality verification should occur during implementation and after completion:

### Pre-Implementation Review
Before writing code, consider:
- **Edge case coverage**: What boundary conditions, error paths, and exceptional cases exist?
- **Input validation**: What inputs need validation? What outputs should be verified?
- **Resource safety**: Are file handles managed properly? Are operations bounded?

### Implementation Quality Gates
During code writing:
- **Error paths**: Operations that can fail should have error handlers.
- **Logging coverage**: Important operations and errors should be logged (where logging exists).
- **Test coverage**: Projects with tests should have tests updated for changes.

### Post-Implementation Verification
After writing code:
- Run the relevant validation commands from the Validation Matrix when available.
- Review changes to ensure existing patterns (logging, testing) are extended consistently.

## Framework Consistency and Technical Debt Prevention
When changing existing code, maintain and extend existing frameworks to prevent regressions:

### Framework Extension
- **Logging**: If the project uses logging, add appropriate log statements for your changes following existing patterns.
- **Testing**: If tests exist, update them for your changes. Add test cases for new functionality.
- **Error handling**: Use established error handling patterns consistently.
- **Documentation**: Update relevant documentation to reflect your changes.

### Consistency Practices
- Match existing code style, naming conventions, and architectural patterns.
- If code validates inputs, extend validation for your changes.
- Complete implementations fully; avoid leaving TODOs without user approval.

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
- Place `bootstrap()` at the top of the file, before any third-party imports.
- Use a user-home dot-directory for the venv (e.g. `~/.editdb_venv`) so it survives working-directory changes.
- Print brief progress messages during first-time setup so the user knows what's happening.
- The script must be a single entry point — no separate `setup.sh` required for end users.
- This avoids PEP 668 / "Externally Managed Environment" issues on macOS/Homebrew systems.

When this does **not** apply:
- Single-file HTML/JS apps (no Python, no dependencies to manage).
- Projects that already use Docker as their delivery mechanism.
- Libraries or packages meant for `pip install` distribution.

### UI: Embedded React SPA (instead of Streamlit)
When a project needs a local web UI, prefer the **embedded single-file React SPA** pattern from `editdb` over Streamlit. This gives desktop-like responsiveness, full layout control, and zero Node.js build tooling.

Stack (all loaded via CDN — no `npm install`, no `node_modules`):
- **React 18** (UMD production build from unpkg)
- **ReactDOM 18** (UMD production build from unpkg)
- **Babel Standalone** (in-browser JSX transpilation)
- **Tailwind CSS** (CDN build with inline config)
- **Lucide Icons** (UMD build from unpkg)

Architecture:
- The Python backend (FastAPI + uvicorn) serves a single HTML template via a `GET /` route.
- All React/JSX, CSS, and Tailwind config are embedded in that HTML string inside the Python file.
- The frontend communicates with the backend exclusively through `fetch()` calls to `/api/*` JSON endpoints.
- State is managed with React `useState`/`useEffect` hooks — no Redux or external state library needed.
- Dark mode uses Tailwind's `darkMode: 'class'` strategy with localStorage persistence.
- An `ErrorBoundary` component wraps the app to catch and display React errors gracefully.

Why this over Streamlit:
- **Performance**: Client-side rendering is instant; Streamlit reruns the entire script on every interaction.
- **Layout control**: Full CSS/Tailwind grid and flexbox vs. Streamlit's limited column model.
- **Inline editing**: React state makes editable tables, modals, and complex interactions natural.
- **Single file**: Everything lives in one Python file — no separate frontend build, no `node_modules`.
- **No extra runtime**: No `pip install streamlit` (30+ transitive deps); just `fastapi` + `uvicorn`.

When this does **not** apply:
- Quick prototypes or throwaway data exploration where Streamlit's speed-to-first-render matters more than UX polish.
- Projects where the user explicitly requests Streamlit.

## Execution Guidance for Agents
- Prefer `rg`/`rg --files` for discovery.
- Prefer minimal, targeted diffs over broad formatting sweeps.
- Update documentation when behavior, interfaces, or run commands change.
- If a change touches multiple projects, validate each project independently with the commands above.
