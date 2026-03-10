# Cognitive Switchyard

A single-user, local-first task orchestration engine that coordinates parallel execution of arbitrary workloads through a multi-phase pipeline. It manages task intake, planning, dependency resolution, parallel dispatch with constraint enforcement, execution, verification, and auto-fix -- with a real-time web UI for monitoring and management.

## Core Concepts

**Workload-agnostic.** The engine owns the *when* and *where* of execution. Workload-specific behavior is defined by **runner packs** -- pluggable configuration bundles that specify how each pipeline phase operates for a given task type (coding with Claude Code, video transcoding with ffmpeg, media downloading with youtube-dl, etc.).

**Idempotent restart.** If the orchestrator crashes or the machine loses power, re-running the same command resumes from where it left off. No manual cleanup, no data loss, no duplicate work.

**Not** a multi-tenant server, a credential manager, or an agent framework. It *uses* agentic CLIs as executors -- it does not implement agent logic itself.

## Pipeline

```
Intake --> Planning --> Staging --> Resolution --> Ready --> Execution --> Done
                         |                                    |
                       Review                              Blocked
                     (human input)                     (needs escalation)
```

Packs declare which phases they use. All phases are optional except Execution.

- **Intake** -- Raw work items as markdown files dropped into a directory
- **Planning** -- Convert intake items into detailed execution plans (LLM-driven)
- **Resolution** -- Analyze all plans to determine dependencies, mutual exclusions, and execution order
- **Execution** -- Dispatch tasks to parallel worker slots with constraint enforcement
- **Verification** -- Global verification suite after task batches complete
- **Auto-Fix** -- Automatically attempt to fix failures before escalating

## Architecture

```
                    +-----------------+
                    |    Web UI       |
                    |  (React SPA)    |
                    +--------+--------+
                             |
                        WebSocket + REST
                             |
                    +--------+--------+
                    |  FastAPI Server  |
                    +--------+--------+
                             |
          +------------------+------------------+
          |                  |                   |
 +--------+-------+ +-------+--------+ +--------+-------+
 |  Orchestrator   | |  Pack Loader   | |  State Store   |
 |  (scheduler,    | |  (registry,    | |  (SQLite +     |
 |   dispatcher,   | |   lifecycle    | |   file dirs)   |
 |   collector)    | |   hooks)       | |                |
 +--------+-------+ +-------+--------+ +--------+-------+
          |                  |                   |
 +--------+--------+                    +--------+--------+
 |  Worker Slots    |                    |  Session Dirs   |
 |  (subprocess     |                    |  (intake, ready,|
 |   management)    |                    |   workers, done,|
 +---------+--------+                    |   blocked, logs)|
           |                             +-----------------+
 +---------+---------+
 | Pack Hooks        |
 | (isolate_start,   |
 |  execute,         |
 |  verify,          |
 |  isolate_end)     |
 +-------------------+
```

## Tech Stack

- **Backend:** Python, FastAPI, uvicorn, aiosqlite
- **Frontend:** Single-file embedded React 18 SPA (CDN-loaded, no npm/node_modules)
- **State:** SQLite + file-as-state directories
- **Self-bootstrapping:** Single entry point, auto-creates venv on first run

## Data Directories

- `~/.cognitive_switchyard_venv/` -- Python virtual environment (auto-created)
- `~/.cognitive_switchyard/` -- Runtime data
  - `cognitive_switchyard.db` -- SQLite database
  - `config.yaml` -- Global settings
  - `packs/` -- Runner pack configurations
  - `sessions/<id>/` -- Per-session artifacts (intake, plans, logs, results)

## Runner Packs

A pack is a directory containing:

```
packname/
  pack.yaml          # Metadata, phase config, capabilities
  prompts/           # Agent prompts (planner, resolver, worker, fixer, system)
  scripts/           # Lifecycle hooks (isolate_start, execute, verify, etc.)
  templates/         # Templates for intake items, plans, status files
```

Built-in pack syncing is planned for a later packet. For now, the repository only validates pack-manifest parsing against curated fixtures.

## Constraint System

- **DEPENDS_ON** -- Hard dependency: task waits until all dependencies reach `done/`
- **ANTI_AFFINITY** -- Mutual exclusion: task waits until no conflicting tasks are active
- **EXEC_ORDER** -- Tiebreaker for dispatch priority among eligible tasks

## Documentation

- [Design Document](docs/cognitive_switchyard_design.md) -- Full specification
- [Packet Loop Orchestrator Design](docs/codex_packet_loop_orchestrator_design.md) -- Design of the packet automation loop and its supported agent CLIs
- `reference/` -- Production orchestration system that Cognitive Switchyard was extracted from (read-only reference material)

## Running

The currently validated run paths are:

```bash
./switchyard --help
./switchyard paths
./switchyard packs
./switchyard sync-packs
./switchyard start --session demo --pack claude-code
```

`./switchyard` remains a thin shim over `python -m cognitive_switchyard`. The package entrypoint now self-bootstraps the private `~/.cognitive_switchyard_venv`, creates the canonical runtime home under `~/.cognitive_switchyard`, writes a default `config.yaml`, and syncs bundled built-in packs into the runtime pack directory.

For development and local validation, use the project venv directly:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m cognitive_switchyard --help
```

## Validation

Use the project virtual environment for tests and validation in Homebrew-managed Python environments:

```bash
.venv/bin/python -m pytest tests -v
```

Useful smoke checks for the current validated surface:

```bash
.venv/bin/python -m cognitive_switchyard --help
./switchyard --help
./switchyard paths
./switchyard packs
```

Operator-facing `serve` and `RELEASE_NOTES.md` emission are not implemented yet.

## Status

The live repository currently implements validated packets `00` through `09`, plus the packet-`10` CLI/bootstrap surface:

- Importable `cognitive_switchyard` package
- Root `switchyard` launcher wired to the package entrypoint
- Minimal CLI help surface that freezes the canonical runtime paths
- Runtime path helpers for the canonical `~/.cognitive_switchyard` layout
- Pure `pack.yaml` parsing and validation for pack/session contracts
- Task-artifact parsers for plans, status sidecars, progress lines, and `resolution.json`
- Pure scheduler-core logic for eligibility and deterministic next-task selection
- The first SQLite-backed state-store/filesystem projection layer for sessions, tasks, worker slots, and events
- Packet-scoped pack hook discovery, executable-bit preflight scanning, prerequisite checks, and short-lived hook execution helpers
- Packet-local worker subprocess dispatch, progress parsing, per-slot log capture, status-sidecar collection, and timeout handling
- The first execution-only orchestrator loop over already-ready tasks, including pack preflight, isolation-hook handoff, session events, and blocked-frontier reporting
- Execution-phase crash recovery, persisted per-slot recovery metadata, filesystem-to-SQLite reconciliation, and restart handling for `running` and `paused` sessions
- Planning and resolution runtime over intake, staging, review, ready, and execution handoff
- Verification and bounded auto-fix retries with restart replay support
- Self-bootstrapping CLI startup, canonical runtime config creation, built-in pack sync/reset, runtime pack listing, and headless session start/resume
- Initial `tests/` tree and curated fixtures for packet-scoped validation

FastAPI/REST, WebSocket transport, the embedded SPA, and later operator tooling/documentation packets are not implemented yet.
