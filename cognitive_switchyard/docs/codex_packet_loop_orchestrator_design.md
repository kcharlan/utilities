# Codex Packet Loop Orchestrator Design

## Purpose

This document describes the intent and operating model of `scripts/codex_packet_loop.zsh`.

It is not the product design for Cognitive Switchyard itself. It is the design for the meta-orchestrator that drives packetized implementation work against this repository using Codex.

The goal is to make the automation understandable and maintainable without reverse engineering the shell script from scratch later.

## Scope

The orchestrator owns:

- packet bootstrap from the packetization playbook
- limited-horizon packet planning
- single-packet implementation
- single-packet validation
- periodic cumulative drift audits
- optional cooperative stop requests
- optional auto-commit after validated packets

It does not own:

- the underlying Cognitive Switchyard product runtime
- packet content semantics beyond prompt contracts
- any direct project-specific business logic

## Inputs

Primary inputs:

- `docs/design_doc_packetization_playbook.md`
- `docs/cognitive_switchyard_design.md`
- `docs/implementation_packet_playbook.md`
- `plans/packet_status.md`
- `plans/packet_status.json`
- packet docs under `plans/`
- current repository state
- read-only reference material under `reference/work/`

## High-Level Flow

The orchestrator runs a constrained loop:

1. `bootstrap` if packetization artifacts are missing
2. `planner` when no actionable packet docs remain
3. `implementer` for exactly one packet
4. `validator` for exactly one packet
5. `drift auditor` periodically and at final completion

Normal steady-state operation is:

`plan -> implement -> validate -> maybe drift audit -> repeat`

## Stage Intent

### Bootstrap

Bootstrap converts the product design doc plus packetization playbook into the working packet system:

- `docs/implementation_packet_playbook.md`
- `plans/packet_status.md`
- `plans/packet_status.json`
- initial packet docs

Bootstrap only runs when those core artifacts are missing.

### Planner

Planner extends the packet frontier by producing only the next narrow horizon of packet docs. It must reconcile packet tracker state with the live codebase instead of trusting stale plan docs.

### Implementer

Implementer works on exactly one packet. It is instructed to stay within packet scope, write tests first, and avoid starting later packets.

### Validator

Validator is packet-local. It reviews the current packet implementation for correctness, regressions, weak tests, and scope creep. It may repair issues inside packet scope and is responsible for advancing packet status to `validated` or `blocked`.

### Drift Auditor

Drift audit is cumulative rather than packet-local. It compares:

- current validated frontier
- packet ladder and tracker state
- cumulative code changes
- design-doc constraints
- implementation playbook contracts

This stage exists to catch broad architectural drift that packet-local validation can miss.

## Drift Audit Cadence

The orchestrator runs drift audit:

- every `DRIFT_AUDIT_INTERVAL` newly validated packets
- after the very next validated packet when the prior drift audit returned `warn`
- once at the end when the project reaches completion

The persisted scheduler state lives in:

- `audits/drift_audit_state.json`

This state tracks the last audited validated count, next due point, and whether the final audit has already been satisfied.

## Drift Audit Result Contract

Every drift audit writes:

- `audits/drift_audit_<label>.md`
- `audits/drift_audit_<label>.json`

The JSON result contains:

- `status`: `pass | fix_now | warn | halt`
- `severity`: `low | medium | high`
- `effort`: `small | medium | high`
- `summary`
- `fixes_applied`
- `validation_rerun`
- `notes`

Interpretation:

- `pass`: continue normally
- `fix_now`: allowed only for low-severity, small-effort repairs performed during the audit
- `warn`: continue, but tighten audit cadence to the next validated packet
- `halt`: stop the automation run because drift is too severe to continue safely

## State Model

The orchestrator depends on tracker state rather than in-memory progress:

- packet state comes from `plans/packet_status.json`
- actionable packet selection is recomputed each cycle
- drift-audit cadence comes from `audits/drift_audit_state.json`
- stop intent comes from a filesystem flag

This is what allows a run to be interrupted and restarted without requiring a bespoke session database.

## Stop Semantics

The orchestrator supports a cooperative stop flag:

- request stop with `stop`
- clear it with `clear-stop`

The flag is checked after stage boundaries, not mid-stage. This is deliberate. The automation avoids interrupting an active `codex exec` stage and instead exits cleanly after the current stage completes.

For an already-running shell process that loaded an older version of the script, new stop behavior does not apply retroactively.

## Auto-Commit Semantics

When `AUTO_COMMIT_VALIDATED=true`, the orchestrator commits after a packet reaches `validated`.

The commit is intentionally narrow:

- packet-scoped files derived from the packet doc's `Allowed Files`
- `plans/packet_status.md`
- `plans/packet_status.json`
- the packet validation audit note under `audits/`

This is opt-in because auto-committing in a dirty worktree can be risky if the file-selection rules are wrong or if the packet doc is inaccurate.

## Service Tier and Model Controls

All Codex stages share the main model selection and can optionally receive a service-tier override:

- `MODEL_NAME`
- `SERVICE_TIER`
- per-stage reasoning effort variables such as `PLANNER_EFFORT`, `VALIDATOR_EFFORT`, `AUDIT_EFFORT`

`SERVICE_TIER=fast` is passed through as a Codex config override for each non-interactive stage.

## Generated Artifacts

Operational artifacts are written to:

- `automation_logs/<timestamp>/` for per-run prompts, event logs, and last messages
- `audits/` for validator and drift-audit reports

The automation log directory is ephemeral run output. The audit directory is part of the durable orchestration record.

## Resumability and Idempotency

The orchestrator is intended to be resumable at stage boundaries:

- if interrupted after implementation but before validation, a rerun should resume at validation
- if interrupted after validation, a rerun should continue from the next packet
- if interrupted before a drift audit completes, packet tracker state remains authoritative and the run can continue safely

This is not perfect transactional idempotency. It is practical stage-boundary resumability based on durable tracker files.

## Known Tradeoffs

- Drift audit is triggered after validated packets, not before beginning the next packet. This favors simpler trigger logic over earliest-possible enforcement.
- The stop flag is stage-boundary only. This avoids corrupting active work but can delay exit until a long validator or drift audit finishes.
- Auto-commit relies on packet docs accurately listing `Allowed Files`. If the packet boundary docs drift from reality, commit selection can become too narrow or too broad.
- The orchestrator is implemented in zsh for pragmatism and portability within the repo, not because shell is the ideal long-term language for this logic.

## Operator Interface

The script's built-in help is the intended operator reference for commands and environment toggles:

```bash
./scripts/codex_packet_loop.zsh --help
```

This should be kept current enough that a separate step-by-step user manual is unnecessary for normal use.
