# Cognitive Switchyard

A single-user, local-first task orchestration engine that coordinates parallel execution of arbitrary workloads through a multi-phase pipeline. It manages task intake, planning, dependency resolution, parallel dispatch with constraint enforcement, execution, verification, and auto-fix -- with a real-time web UI for monitoring and management.

## Core Concepts

**Workload-agnostic.** The engine owns the *when* and *where* of execution. Workload-specific behavior is defined by **runner packs** -- pluggable configuration bundles that specify how each pipeline phase operates for a given task type (coding with Claude Code, video transcoding with ffmpeg, media downloading with youtube-dl, etc.).

**Idempotent restart.** If the orchestrator crashes or the machine loses power, re-running the same command resumes from where it left off. No manual cleanup, no data loss, no duplicate work.

**Not** a multi-tenant server, a credential manager, or an agent framework. It *uses* agentic CLIs as executors -- it does not implement agent logic itself.

## Pipeline

```
Intake --> Planning --> Staging --> Resolution --> Ready --> Execution --> Verify --> Done
                         |                                    |             |
                       Review                              Blocked      Auto-Fix
                     (human input)                     (needs escalation)
```

Packs declare which phases they use. All phases are optional except Execution.

- **Intake** -- Raw work items as markdown files dropped into a directory
- **Planning** -- Convert intake items into detailed execution plans (LLM-driven, with streaming output)
- **Resolution** -- Analyze all plans to determine dependencies, mutual exclusions, and execution order
- **Execution** -- Dispatch tasks to parallel worker slots with constraint enforcement
- **Verification** -- Global test suite after task batches complete (interval-based, task-triggered, and mandatory final)
- **Auto-Fix** -- Automatically attempt to fix failures with bounded retries before escalating

## Session Worktree Isolation

When a session is created with both `COGNITIVE_SWITCHYARD_REPO_ROOT` and `COGNITIVE_SWITCHYARD_BRANCH` environment variables, the backend creates a git worktree in a peer directory of the source repo. Workers operate on the worktree, leaving the original repository untouched. Worktrees are cleaned up automatically when sessions complete, abort, or are deleted.

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

- **Backend:** Python 3.12+, FastAPI, uvicorn, aiosqlite, PyYAML
- **Frontend:** Single-file embedded React 18 SPA (CDN-loaded, no npm/node_modules)
- **State:** SQLite + file-as-state directories
- **Self-bootstrapping:** Single entry point, auto-creates venv on first run

## Quick Start

```bash
# Web UI mode (recommended)
./switchyard serve

# Headless CLI mode
./switchyard start --session my-session --pack claude-code
```

The `serve` command starts a FastAPI server with the embedded React SPA. Sessions are created and managed through the web UI, which provides real-time monitoring of all pipeline stages.

On first run, `./switchyard` self-bootstraps a private venv at `~/.cognitive_switchyard_venv/`, creates the runtime home at `~/.cognitive_switchyard/`, writes a default `config.yaml`, and syncs built-in packs.

## Data Directories

- `~/.cognitive_switchyard_venv/` -- Python virtual environment (auto-created)
- `~/.cognitive_switchyard/` -- Runtime data
  - `cognitive_switchyard.db` -- SQLite database
  - `config.yaml` -- Global settings (retention, default worker/planner counts, default pack)
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

Built-in packs:

| Pack | Description |
|------|-------------|
| `claude-code` | Claude Code CLI as the execution engine for coding tasks |
| `codex` | OpenAI Codex CLI as an alternative execution engine |
| `test-echo` | Minimal test pack that echoes inputs (for development/testing) |

Packs are synced to the runtime directory on first run and can be refreshed with `./switchyard sync-packs` or reset individually with `./switchyard reset-pack <name>`.

## Web UI

The embedded React SPA provides four views:

- **Setup** -- Create sessions, configure packs, set repo root/branch for worktree isolation, run preflight checks, manage intake items
- **Monitor** -- Real-time pipeline strip, streaming phase logs (planning/resolution/execution), worker cards with progress bars and log tails, verification progress countdown, auto-fix attempt tracking
- **History** -- Browse completed/aborted sessions, view release notes and task outcomes
- **Settings** -- Global configuration (retention, default counts, default pack)

Real-time updates flow through WebSocket: state changes, task status transitions, worker log lines, progress detail markers, and alerts.

## Constraint System

- **DEPENDS_ON** -- Hard dependency: task waits until all dependencies reach `done/`
- **ANTI_AFFINITY** -- Mutual exclusion: task waits until no conflicting tasks are active
- **EXEC_ORDER** -- Tiebreaker for dispatch priority among eligible tasks

## Verification System

Three triggers fire the verification command:

1. **Interval** -- Every N completed tasks (configurable, default 4)
2. **Task-driven** -- Tasks with `FULL_TEST_AFTER: yes` force immediate verification
3. **Final** -- Mandatory verification before declaring a session complete

When verification fails, the auto-fix loop runs the fixer agent up to N attempts (configurable), re-verifying after each fix. If all attempts fail, the session pauses for operator intervention.

## CLI Reference

```bash
./switchyard --help                              # Show all commands
./switchyard paths                               # Print canonical runtime paths
./switchyard packs                               # List available runtime packs
./switchyard sync-packs                          # Sync built-in packs to runtime
./switchyard reset-pack <name>                   # Reset a built-in pack to factory
./switchyard init-pack <name>                    # Scaffold a new custom pack
./switchyard validate-pack <path>                # Validate pack structure and config
./switchyard start --session <id> --pack <name>  # Start a headless session
./switchyard serve                               # Start the web UI server
```

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest tests/ -v
```

The test suite covers all modules with ~195 tests across unit, integration, and E2E layers. E2E tests require Playwright (`pip install pytest-playwright && playwright install`).

```bash
# Run unit/integration tests (fast)
pytest tests/ --ignore=tests/test_e2e.py --ignore=tests/test_cli.py

# Run E2E tests (requires Playwright + running server)
pytest tests/test_e2e.py
```

## Documentation

- [Design Document](docs/cognitive_switchyard_design.md) -- Full specification
- [Packet Loop Orchestrator Design](docs/codex_packet_loop_orchestrator_design.md) -- Design of the packet automation loop and its supported agent CLIs
- [Pack Author Guide](docs/pack_author_guide.md) -- How to create, validate, and iterate on custom runtime packs
- [Operator Guide](docs/operator_guide.md) -- How to bootstrap, run, monitor, and troubleshoot local sessions
- [Built-In Claude Code Pack Guide](docs/builtin_claude_code_pack.md) -- Claude Code pack prerequisites, prompts, and customization points
- [Built-In Codex Pack Guide](docs/builtin_codex_pack.md) -- Codex pack prerequisites, prompts, and customization points
- [Lessons Learned](docs/LESSONS_LEARNED.md) -- Bug patterns and debugging insights
