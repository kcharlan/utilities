# Pack Audit 20260307

## Assumptions

- **Delivery model**: Built-in packs are operator-facing templates shipped with the repository and expected to be safe to validate and run on a local development machine.
- **Trust boundary**: `test-echo` and `ffmpeg-transcode` are single-user local packs; their plan files are assumed to be authored by the operator, not untrusted remote input.
- **Runtime model**: `claude-code` is expected to run through the Cognitive Switchyard orchestrator, not by invoking its helper scripts directly.
- **Repository safety expectation**: A built-in pack must never contain hardcoded paths to another local repository or legacy pipeline tree.
- **Validation expectation**: `validate-pack` should catch known-dangerous built-in pack defects before execution.

## Rules / Standards Applied

### Correctness / Safety

- Built-in prompts must be runtime-neutral and must not reference a different repository or legacy orchestration paths.
- Isolation hooks for worktree-based execution must be invoked and must preserve successful work before cleanup.

### Robustness & Resilience

- Helper scripts that are not true entrypoints should fail safely when invoked directly.
- Verification scripts should prefer the project venv over ambient global tooling.

### Best Practices & Maintainability

- Agent prompt files should rely on orchestrator-injected runtime context rather than copied reference-system transcripts.
- Pack validation should include prompt safety checks for known-dangerous path patterns.

## Findings

### [Correctness / Safety] Finding #1: Claude Pack Prompts Referenced A Different Repository And Legacy Pipeline Paths

- **Severity**: Critical
- **Category**: Correctness & Safety
- **Evidence**:
  - `packs/claude-code/prompts/system.md` previously hardcoded `/Users/kevinharlan/source/benefit_specification_engine`
  - `packs/claude-code/prompts/planner.md`, `packs/claude-code/prompts/resolver.md`, and `packs/claude-code/prompts/worker.md` previously instructed the agent to use `work/planning/...`, `work/execution/...`, and `execution/active/...`
- **Impact**:
  - Best case: the pack fails because the referenced paths do not exist in the current repo
  - Worst case: the agent edits or reads from an unrelated repository on disk
  - This violates the local-project safety boundary for built-in packs
- **Recommended Fix**:
  - Rewrite the Claude prompts to use `## SWITCHYARD_CONTEXT` as the sole runtime source of truth
  - Remove all hardcoded absolute paths and reference-system directory instructions
  - Add validation rules that fail packs containing these patterns
- **Effort**: S
- **Risk**: Low
- **Acceptance Criteria**:
  - `rg -n '/Users/|work/planning/|work/execution/|execution/active/|benefit_specification_engine' packs/claude-code/prompts` returns no matches
  - `.venv/bin/python -m cognitive_switchyard validate-pack packs/claude-code` passes

### [Correctness / Safety] Finding #2: Git Worktree Teardown Hook Was Defined But Never Invoked

- **Severity**: High
- **Category**: Correctness & Safety
- **Evidence**:
  - `cognitive_switchyard/orchestrator.py` previously invoked `isolation.setup` but never called `isolation.teardown`
  - `packs/claude-code/scripts/isolate_end` existed but was unreachable in the normal execution path
- **Impact**:
  - Successful Claude tasks would not merge their worktree branch back to the main checkout
  - Worktree directories and temporary branches would accumulate after each run
  - The `claude-code` pack could report task success without delivering the code change
- **Recommended Fix**:
  - Invoke the teardown hook from worker completion handling
  - Treat teardown failure as a blocking failure rather than silent success
  - Ensure the Claude teardown script merges successful branches before removing the worktree
- **Effort**: M
- **Risk**: Medium
- **Acceptance Criteria**:
  - A temp-repo test proves `isolate_start` + `isolate_end done` merges a committed worktree change and removes the worktree
  - Full pytest suite remains green

### [Robustness & Resilience] Finding #3: Claude Execute Helper Script Looked Runnable But Did Not Receive Safe Runtime Context

- **Severity**: Medium
- **Category**: Robustness & Resilience
- **Evidence**:
  - `packs/claude-code/scripts/execute` previously read the worker prompt directly and appended only ad hoc `Plan file:` / `Workspace:` strings
  - The real runtime path for `agent` execution is orchestrator-driven, not this script
- **Impact**:
  - Direct invocation could launch Claude with incomplete runtime information
  - Operators or future code could mistake the helper for the supported entrypoint
- **Recommended Fix**:
  - Make the script fail fast with an explicit message that the orchestrator agent runtime is the supported entrypoint
  - Keep the actual runtime path in the orchestrator
- **Effort**: S
- **Risk**: Low
- **Acceptance Criteria**:
  - Direct invocation exits non-zero with a clear message
  - Orchestrated `agent` execution tests still pass

### [Best Practices & Maintainability] Finding #4: Pack Validation Did Not Inspect Prompt Files For Dangerous Path Leakage

- **Severity**: Medium
- **Category**: Best Practices & Maintainability
- **Evidence**:
  - `cognitive_switchyard/pack_loader.py` previously validated only `pack.yaml` and referenced script executability
  - Prompt files could embed dangerous runtime assumptions without any validation failure
- **Impact**:
  - A pack could pass validation while still being unsafe to run
  - Regressions of the Claude prompt defect would be easy to reintroduce
- **Recommended Fix**:
  - Extend `validate_pack_path()` to scan prompt files for known-dangerous path patterns
  - Add regression tests covering prompt-path validation
- **Effort**: S
- **Risk**: Low
- **Acceptance Criteria**:
  - Validation fails on a pack containing hardcoded `/Users/...` or `work/planning/...` references
  - Validation passes on the corrected built-in packs

## Other Pack Review Notes

- `packs/test-echo`: No safety issues found beyond its intentionally trivial behavior. It stays within the provided plan path and writes a local sidecar.
- `packs/ffmpeg-transcode`: No hardcoded path defects found. Residual risk is operator-controlled output/argument selection, which is expected for a local ffmpeg wrapper pack. No code change recommended from this audit.
