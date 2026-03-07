## Assumptions

- **Reference scope**: `reference/work/` is treated as the authoritative semantic source for the original Claude-driven pipeline, even where some operator docs are slightly stale relative to the shell scripts.
- **Current target**: `cognitive_switchyard` is intended to preserve the original pipeline's safety and operator semantics for the `claude-code` pack while generalizing the runtime for other packs.
- **Deployment model**: single-user local execution with a file-backed session directory, SQLite state, and optional git worktree isolation.
- **Validation model**: pack-level verification commands are intended to stand in for the reference system's hardcoded repo-specific full-suite commands.

## Reference Intent Summary

### Operator docs and generated artifacts

- `reference/work/README.md`: operator-facing guide for running, monitoring, and recovering the pipeline.
- `reference/work/USER_PROCESS.md`: prescriptive workflow for intake -> planning -> review -> resolution -> orchestration.
- `reference/work/RUNBOOK_v0.1.79.md`: example of the downstream operator artifact the pipeline is meant to support; not an engine primitive.
- `reference/work/DASHBOARD.md`: generated status surface for queue counts, active workers, constraints, and monitoring commands.
- `reference/work/RELEASE_NOTES.md`: generated aggregation of plan metadata and operator actions from completed work.

### Shared rules and prompts

- `reference/work/SYSTEM.md`: shared invariants. File location is state; branch safety matters; `.venv/bin/pytest` is required; review and auto-fix are first-class; operator actions must survive planning and execution.
- `reference/work/planning/PLANNER.md`: planner loop, review/revision semantics, frontmatter schema, testing requirements, split-plan rules, and operator-actions requirements.
- `reference/work/execution/RESOLVER.md`: batch dependency analysis, in-place metadata updates, anti-affinity computation, and human-readable resolution reporting.
- `reference/work/execution/WORKER.md`: strict worker lifecycle, progress markers, checkpoint commits, regression/e2e expectations, and sidecar requirements.

### Control scripts

- `reference/work/plan.sh`: launches parallel planners that autonomously drain intake, checks plan ID collisions, and reports review/staging outcomes.
- `reference/work/stage.sh`: launches a single batch resolver pass over all staged plans.
- `reference/work/orchestrate.sh`: branch guard, crash recovery, dependency-aware dispatch, worktree lifecycle, merge policy, full-suite cadence, auto-fix, dashboard generation, and final release-note generation.
- `reference/work/generate_release_notes.sh`: aggregates `## Operator Actions` and plan/status metadata from `done/` into an operator-readable release note artifact.

### Sample artifacts

- `reference/work/execution/RESOLUTION.md`: expected resolver output shape and constraint vocabulary.
- `reference/work/execution/done/*.plan.md`, `*.status`, `*.log`: examples of the plan/status/log contract the runtime is expected to preserve.

## Findings

### [Correctness/Safety] Finding #1: Failed Claude runs do not preserve worktrees for recovery

- **Severity**: Critical
- **Category**: Correctness & Safety
- **Evidence**:
  - Current: `/Users/kevinharlan/source/utilities/cognitive_switchyard/cognitive_switchyard/orchestrator.py:477`
  - Current: `/Users/kevinharlan/source/utilities/cognitive_switchyard/packs/claude-code/scripts/isolate_end:15`
  - Reference: `/Users/kevinharlan/source/utilities/cognitive_switchyard/reference/work/orchestrate.sh:746`
- **Impact**:
  - A blocked worker loses its worktree before the plan is escalated.
  - Manual diagnosis and crash recovery lose the exact failing git state the reference system intentionally preserved.
  - The `claude-code` pack no longer meets the reference workflow's "preserve worktree on failure" invariant.
- **Why this happened**:
  - Isolation teardown is now invoked before blocked handling.
  - The teardown script removes the worktree for both `done` and `blocked` outcomes.
- **Assessment**:
  - Not correct for reference intent.

### [Correctness/Safety] Finding #2: Successful Claude merges use branch-history merge instead of squash merge

- **Severity**: High
- **Category**: Correctness & Safety
- **Evidence**:
  - Current: `/Users/kevinharlan/source/utilities/cognitive_switchyard/packs/claude-code/scripts/isolate_end:15`
  - Reference: `/Users/kevinharlan/source/utilities/cognitive_switchyard/reference/work/orchestrate.sh:670`
  - Reference: `/Users/kevinharlan/source/utilities/cognitive_switchyard/reference/work/execution/WORKER.md:98`
- **Impact**:
  - Worker checkpoint commits can land directly on the main development branch instead of being collapsed into one pipeline commit.
  - Mainline history becomes noisier and departs from the reference system's operator expectations.
- **Why this happened**:
  - The generic teardown hook merges the worker branch with `--ff-only` or `--no-ff` rather than performing the orchestrator-owned squash merge.
- **Assessment**:
  - Functionally workable, but not correct for reference intent.

### [Robustness] Finding #3: Recovery does not clean up orphaned worktrees or worker branches

- **Severity**: High
- **Category**: Robustness & Resilience
- **Evidence**:
  - Current: `/Users/kevinharlan/source/utilities/cognitive_switchyard/cognitive_switchyard/orchestrator.py:130`
  - Reference: `/Users/kevinharlan/source/utilities/cognitive_switchyard/reference/work/orchestrate.sh:114`
- **Impact**:
  - Restart is only partially idempotent for git-isolated packs.
  - Stale worktrees and branches can accumulate across crashes and interfere with later dispatches or operator understanding.
- **Why this happened**:
  - The Python recovery path reconciles slot files and database state but has no pack-aware cleanup pass for isolation artifacts.
- **Assessment**:
  - Not correct for reference intent, especially for `claude-code`.

### [Correctness/Safety] Finding #4: `FULL_TEST_AFTER` is authored but never consumed by the orchestrator

- **Severity**: High
- **Category**: Correctness & Safety
- **Evidence**:
  - Current prompt still requires the field: `/Users/kevinharlan/source/utilities/cognitive_switchyard/packs/claude-code/prompts/planner.md:57`
  - Current verification trigger ignores it: `/Users/kevinharlan/source/utilities/cognitive_switchyard/cognitive_switchyard/orchestrator.py:408`
  - Reference uses it to force a full run: `/Users/kevinharlan/source/utilities/cognitive_switchyard/reference/work/orchestrate.sh:682`
- **Impact**:
  - Plans can correctly identify "run the full suite immediately after this" and the runtime will ignore that request.
  - Safety-sensitive changes rely only on the fixed interval instead of plan-specific forcing.
- **Why this happened**:
  - The current runtime kept interval-based verification but did not add a metadata-driven override.
- **Assessment**:
  - Not correct for reference intent.

### [Correctness/Safety] Finding #5: The `claude-code` pack lacks the reference branch-safety guard

- **Severity**: High
- **Category**: Correctness & Safety
- **Evidence**:
  - Current setup script creates worktrees from whatever branch is checked out: `/Users/kevinharlan/source/utilities/cognitive_switchyard/packs/claude-code/scripts/isolate_start:15`
  - Current orchestrator has no equivalent guard: `/Users/kevinharlan/source/utilities/cognitive_switchyard/cognitive_switchyard/orchestrator.py:87`
  - Reference guard: `/Users/kevinharlan/source/utilities/cognitive_switchyard/reference/work/orchestrate.sh:96`
  - Reference rule: `/Users/kevinharlan/source/utilities/cognitive_switchyard/reference/work/SYSTEM.md:147`
- **Impact**:
  - The pipeline can run directly from `main`, which the reference system explicitly forbids.
  - On a coding pack, that weakens the main protection against accidental direct pipeline work on the trunk branch.
- **Why this happened**:
  - The generalized runtime moved branch handling into pack isolation hooks but never reintroduced the guard for the git-worktree coding pack.
- **Assessment**:
  - Not correct for reference intent.

### [Best Practices] Finding #6: Planner concurrency semantics were flattened to single-item planning, but pack config still advertises parallel planners

- **Severity**: Medium
- **Category**: Best Practices & Maintainability
- **Evidence**:
  - Current config advertises planner parallelism: `/Users/kevinharlan/source/utilities/cognitive_switchyard/packs/claude-code/pack.yaml:6`
  - Current runtime plans one intake item at a time: `/Users/kevinharlan/source/utilities/cognitive_switchyard/cognitive_switchyard/orchestrator.py:165`
  - Current planner prompt explicitly says single-item execution: `/Users/kevinharlan/source/utilities/cognitive_switchyard/packs/claude-code/prompts/planner.md:26`
  - Reference planner launcher is a parallel autonomous loop: `/Users/kevinharlan/source/utilities/cognitive_switchyard/reference/work/plan.sh:12`
  - Reference planner launcher also rejects prefix collisions with completed plans: `/Users/kevinharlan/source/utilities/cognitive_switchyard/reference/work/plan.sh:38`
- **Impact**:
  - Throughput is lower than the original design for large intake batches.
  - `planning.max_instances` is currently descriptive only; operators could reasonably assume it is enforced when it is not.
  - The current flow also dropped the original preflight check that prevented reusing a completed numeric plan prefix.
- **Why this happened**:
  - The generalized orchestrator owns the planning queue and invokes the planner per-item.
- **Assessment**:
  - Acceptable as an engine simplification, but the current config and docs should not imply the original behavior is still present.

### [Maintainability] Finding #7: Operator-action aggregation was not carried forward into the runtime

- **Severity**: Medium
- **Category**: Best Practices & Maintainability
- **Evidence**:
  - Current session completion writes `summary.json` and trims logs: `/Users/kevinharlan/source/utilities/cognitive_switchyard/cognitive_switchyard/orchestrator.py:1024`
  - Current repo has no runtime equivalent of the generator script.
  - Reference requirement: `/Users/kevinharlan/source/utilities/cognitive_switchyard/reference/work/SYSTEM.md:124`
  - Reference implementation: `/Users/kevinharlan/source/utilities/cognitive_switchyard/reference/work/generate_release_notes.sh:1`
- **Impact**:
  - Plans still preserve `## Operator Actions`, but the operator no longer gets the aggregated deployment artifact the original system was designed to produce.
- **Why this happened**:
  - The current runtime focused on session/UI summaries and did not port the release-note aggregation step.
- **Assessment**:
  - Not correct if the `claude-code` pack is meant to preserve the full operator workflow.

## Intentional Deviations That Appear Correct

### [Maintainability] Finding #8: Resolver reporting moved from markdown-first to JSON-first

- **Severity**: Low
- **Category**: Best Practices & Maintainability
- **Evidence**:
  - Current runtime consumes `resolution.json`: `/Users/kevinharlan/source/utilities/cognitive_switchyard/cognitive_switchyard/orchestrator.py:289`
  - Current passthrough resolver writes JSON: `/Users/kevinharlan/source/utilities/cognitive_switchyard/cognitive_switchyard/resolution.py:44`
  - Reference writes `RESOLUTION.md`: `/Users/kevinharlan/source/utilities/cognitive_switchyard/reference/work/execution/RESOLVER.md:54`
- **Impact**:
  - Human-readable markdown resolution reporting is reduced, but the machine interface is cleaner for the generalized engine.
- **Why this happened**:
  - The generalized runtime uses SQLite/API/UI state and no longer parses constraints from markdown files.
- **Assessment**:
  - Correct for the generalized engine, as long as human-readable visibility is available elsewhere.

### [Maintainability] Finding #9: Monitoring moved from generated markdown dashboard to API/Web UI state

- **Severity**: Low
- **Category**: Best Practices & Maintainability
- **Evidence**:
  - Current monitoring surface is API/websocket/UI-backed: `/Users/kevinharlan/source/utilities/cognitive_switchyard/cognitive_switchyard/server.py:132`
  - Reference dashboard artifact: `/Users/kevinharlan/source/utilities/cognitive_switchyard/reference/work/DASHBOARD.md:1`
- **Impact**:
  - Operators use a richer UI instead of tailing a markdown file.
- **Why this happened**:
  - The new runtime deliberately replaced file-based monitoring with a stateful service and embedded SPA.
- **Assessment**:
  - Correct intentional redesign.
