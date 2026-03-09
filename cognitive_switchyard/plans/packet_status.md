# Packet Status

Assessed against the live repository on 2026-03-09.

## Current State

- The repository is mostly design and planning material.
- Existing code assets are limited to the root `switchyard` launcher, `requirements.txt`, and planning helpers under `scripts/`.
- There is no importable `cognitive_switchyard` package, no `tests/` tree, no built-in `packs/`, and no backend/runtime implementation yet.
- Validation evidence:
  - `./switchyard --help` currently fails with `ModuleNotFoundError: No module named 'cognitive_switchyard'`.
  - `.venv/bin/python -m pytest tests -v` currently fails because `tests/` does not exist.

## Highest Validated Packet

`none`

## Ladder

| ID | Status | Name | Depends On | Doc | Notes |
|---|---|---|---|---|---|
| `00` | `planned` | Canonical Contracts and Scaffold | `[]` | `plans/packet_00_canonical_contracts_and_scaffold.md` | First packet resolves naming/path contradictions and creates the real package/test baseline. |
| `01` | `planned` | Pack and Session Contract Parsing | `[00]` | `plans/packet_01_pack_and_session_contract_parsing.md` | Pure manifest/config parsing and session directory helpers only. |
| `02` | `planned` | Task Artifact Parsing and Scheduler Core | `[00, 01]` | `plans/packet_02_task_artifact_parsing_and_scheduler_core.md` | Pure parsers and eligibility logic; no DB or subprocesses. |
| `03` | `planned` | SQLite State Store and Filesystem Projection | `[00, 01, 02]` | `plans/packet_03_sqlite_state_store_and_filesystem_projection.md` | Introduces persistence after contracts are stable. |
| `04` | `planned` | Pack Hook Runner and Preflight | `[01]` | `plans/packet_04_pack_hook_runner_and_preflight.md` | Script invocation and executable checks. |
| `05` | `planned` | Worker Slot Lifecycle and Timeout Monitoring | `[02, 04]` | `plans/packet_05_worker_slot_lifecycle_and_timeout_monitoring.md` | Subprocess/log lifecycle isolated from orchestration. |
| `06` | `planned` | Execution Orchestrator Loop | `[03, 05]` | `plans/packet_06_execution_orchestrator_loop.md` | First end-to-end execution pipeline. |
| `07` | `planned` | Crash Recovery and Reconciliation | `[03, 05, 06]` | `plans/packet_07_crash_recovery_and_reconciliation.md` | Idempotent restart and orphan cleanup. |
| `08` | `planned` | Planning and Resolution Runtime | `[03, 04, 06, 07]` | `plans/packet_08_planning_and_resolution_runtime.md` | Planner/resolver phases after execution is stable. |
| `09` | `planned` | Verification and Auto-Fix Loop | `[06, 08]` | `plans/packet_09_verification_and_auto_fix_loop.md` | Global verify and fixer retry behavior. |
| `10` | `planned` | CLI, Bootstrap, and Built-In Pack Sync | `[01, 04, 06, 08]` | `plans/packet_10_cli_bootstrap_and_built_in_pack_sync.md` | User-facing startup surface after engine stabilization. |
| `11` | `planned` | FastAPI REST and WebSocket Backend | `[03, 06, 08, 09]` | `plans/packet_11_fastapi_rest_and_websocket_backend.md` | Stable backend transport surface. |
| `12` | `planned` | Embedded React SPA Monitor | `[11]` | `plans/packet_12_embedded_react_spa_monitor.md` | UI only after REST/WS contracts exist. |
| `13` | `planned` | Built-In Packs, Pack Tooling, and Operator Docs | `[08, 09, 10, 12]` | `plans/packet_13_built_in_packs_pack_tooling_and_operator_docs.md` | Prove generality and ship operator flows last. |

## Next Horizon

Create or work only from these packet docs until one becomes validated:

1. `plans/packet_00_canonical_contracts_and_scaffold.md`
2. `plans/packet_01_pack_and_session_contract_parsing.md`
3. `plans/packet_02_task_artifact_parsing_and_scheduler_core.md`
