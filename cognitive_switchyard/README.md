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

- `~/.switchyard_venv/` -- Python virtual environment (auto-created)
- `~/.switchyard/` -- Runtime data
  - `switchyard.db` -- SQLite database
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

Built-in packs are copied to `~/.switchyard/packs/` on first run. Users can add custom packs by creating new directories there.

## Constraint System

- **DEPENDS_ON** -- Hard dependency: task waits until all dependencies reach `done/`
- **ANTI_AFFINITY** -- Mutual exclusion: task waits until no conflicting tasks are active
- **EXEC_ORDER** -- Tiebreaker for dispatch priority among eligible tasks

## Documentation

- [Design Document](docs/cognitive_switchyard_design.md) -- Full specification
- `reference/` -- Production orchestration system that Cognitive Switchyard was extracted from (read-only reference material)

## Status

**Pre-implementation.** Design document complete, implementation not yet started.
