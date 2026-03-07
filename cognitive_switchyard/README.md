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

Built-in packs are copied to `~/.cognitive_switchyard/packs/` on first run. Users can add custom packs by creating new directories there.

## Constraint System

- **DEPENDS_ON** -- Hard dependency: task waits until all dependencies reach `done/`
- **ANTI_AFFINITY** -- Mutual exclusion: task waits until no conflicting tasks are active
- **EXEC_ORDER** -- Tiebreaker for dispatch priority among eligible tasks

## Documentation

- [Design Document](docs/cognitive_switchyard_design.md) -- Full specification
- `reference/` -- Production orchestration system that Cognitive Switchyard was extracted from (read-only reference material)

## Running

The project has two supported run paths:

```bash
./switchyard --help
```

This is the self-bootstrapping entry point. On first run it creates `~/.cognitive_switchyard_venv/`, installs the runtime dependencies there, and re-executes itself from that private environment.

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

Useful smoke checks:

```bash
./switchyard list-packs
.venv/bin/python -m cognitive_switchyard serve --port 8100
```

## Status

The implementation plan is now covered through Phase 4:

- Core CLI orchestrator, state store, scheduler, worker manager, crash recovery
- Planning, resolution, verification, and auto-fix pipeline phases
- Script-backed and `agent`-backed execution paths
- FastAPI server with embedded React web console
- Built-in `test-echo`, `claude-code`, and `ffmpeg-transcode` packs
- Pack author guide, pack scaffold command, and pack validation command

The remaining practical caveat is external tooling: packs such as `claude-code` still depend on the required third-party CLI and repo/tooling environment being available on the local machine.
