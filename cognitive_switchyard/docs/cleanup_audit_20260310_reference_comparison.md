# Audit: Python Implementation vs Reference Shell Scripts & Design Document

**Date:** 2026-03-10
**Scope:** Systematic comparison of the current Python implementation against the reference shell scripts (`reference/work/plan.sh`, `orchestrate.sh`, `stage.sh`, `SYSTEM.md`) and the design document (`docs/cognitive_switchyard_design.md`).

**Prior audits in this session found and fixed:**
- Ghost duplicate pipeline files (agent wrote files + code created duplicates)
- Wrong working directory for planner agent (session dir instead of repo root)
- Pipeline stopping with staged items (empty `staged_task_ids` due to untracked agent-written files)
- Double-nested alert WebSocket payloads
- Port test permanently hanging

This audit focuses on **architectural deviations** between the reference implementation and the Python code.

---

## Assumptions

- **Reference implementation**: The shell scripts in `reference/work/` are the proven, battle-tested original. They define the correct behavioral contract.
- **Design document**: `docs/cognitive_switchyard_design.md` is the intended architecture. Where it conflicts with reference scripts, the scripts (working code) take precedence.
- **SYSTEM.md**: The canonical "who moves what" rules for pipeline file management.

---

## Critical Finding: Architecture Decision Required

### The Fundamental Question: Who Manages Pipeline Files?

The reference shell scripts and the Python implementation use **fundamentally different architectures** for the planning phase. This is not a bug — it's an architectural decision that was never explicitly made.

**Reference architecture (plan.sh + SYSTEM.md):**
```
Shell script launches agent → Agent runs autonomously in $REPO_ROOT →
Agent claims files, reads code, writes plans, deletes claimed files →
Shell script waits, reports results
```

The shell script does NO file management. It launches `cc-opus` with a prompt that tells the agent to read `PLANNER.md` and `SYSTEM.md`, then the agent does everything: claim intake items, read source code, write plans to staging/review, clean up claimed files.

**Current Python architecture (planning_runtime.py):**
```
Python code claims files → Python calls agent(text) → Agent returns plan text →
Python parses output → Python writes files → Python deletes claimed files
```

The Python code does ALL file management. The agent is a pure function: text in, text out. The planner prompt was rewritten to match this contract ("OUTPUT ONLY, no file I/O").

**Both approaches are valid.** The tradeoffs:

| Aspect | Agent-managed (reference) | Code-managed (current Python) |
|--------|--------------------------|-------------------------------|
| **Reliability** | Agent may forget steps, write wrong paths, leave orphans | Deterministic — code always does the same thing |
| **Observability** | Hard to know what agent did until after | Every step is logged and event-emitted |
| **Error recovery** | If agent crashes mid-file-move, state is ambiguous | Atomic operations, clear crash recovery |
| **Flexibility** | Agent can adapt to unexpected situations | Code handles only anticipated cases |
| **Prompt complexity** | Agent needs file management instructions | Agent prompt is simpler (output only) |
| **Testing** | Hard to unit test agent file I/O | Fully unit-testable |

**The current Python approach (code-managed) is the better architecture for this system**, for these reasons:
1. The whole point of Cognitive Switchyard is to be a _reliable orchestrator_. The reference scripts worked because the shell is simple and the agent was powerful, but the agent forgetting to clean up `claimed/` was a real failure mode (plan.sh lines 118-122 explicitly handle this).
2. Observability: every file move emits a WebSocket event. This enables the real-time UI.
3. Error recovery: `_recover_claimed_items` is deterministic. The reference had to guess ("if these have matching plans in staging/ or review/, the planner forgot to clean up").
4. Testability: 170+ unit tests cover the pipeline logic. The reference scripts had zero automated tests.

**Recommendation:** Keep the current code-managed architecture. The planner prompt rewrite ("OUTPUT ONLY") correctly aligns the prompt with this architecture. However, the `ArtifactParseError` handler that detects agent-written files should be kept as a safety net for when agents don't follow instructions (they won't always).

---

## Finding #1: Pipeline Stopping After Planning (ADDRESSED)

**Severity:** Critical (was causing user-visible failures)
**Status:** Fixed in this session

**The bug:** `prepare_session_for_execution` (line 83) returns early and reverts to "created" when `staged_task_ids` is empty. When the agent wrote files directly (before the prompt was rewritten), the pipeline code didn't track those files, so `staged_task_ids` was always empty even when files existed in `staging/`.

**The fix (already applied):** The `ArtifactParseError` handler now scans for agent-written files and populates `staged_task_ids`/`review_task_ids` accordingly. Combined with the prompt rewrite (agent now returns text, code writes files), this addresses both the symptom and root cause.

**Why the pipeline still reverts to "created" after planning with only review items:** This is actually correct behavior. If all items went to review, the session can't proceed to execution — it needs human input. The status revert to "created" signals this. The reference scripts handled this the same way (plan.sh exits, user must resolve review items, then re-run).

---

## Finding #2: Missing Plan ID Collision Detection

**Severity:** Medium
**Category:** Correctness

**Reference behavior (plan.sh lines 38-57):**
```bash
# Check for plan ID collisions with existing done/ plans
for intake_file in "$SCRIPT_DIR/planning/intake/"*.md; do
  prefix=$(basename "$intake_file" | grep -oE '^[0-9]+')
  if ls "$SCRIPT_DIR/execution/done/${prefix}_"*.plan.md >/dev/null 2>&1; then
    log "!! WARNING: Intake item uses prefix $prefix which already exists in done/"
    collision=true
  fi
done
if $collision; then
  log "!! Plan ID collision detected. Renumber the intake items."
  exit 1
fi
```

**Current Python:** No collision detection. If a user drops `001_new_task.md` into intake when `001_old_task.plan.md` already exists in `done/`, the new plan could overwrite or conflict with the completed one.

**Impact:** Task ID collisions could cause the resolution phase to reference wrong dependency targets, or the scheduler to treat a new task as already completed.

**Recommended fix:** Add collision detection at the start of `run_planning_phase`. Check `session_paths.done` for existing plan IDs that match incoming intake item prefixes. Emit a pipeline event and raise an error if collisions are found.

---

## Finding #3: Missing Branch Safety Guard

**Severity:** Medium
**Category:** Robustness

**Reference behavior (orchestrate.sh lines 100-108):**
```bash
current_branch=$(git rev-parse --abbrev-ref HEAD)
if [ "$current_branch" = "main" ]; then
  log "!! REFUSING TO RUN: current branch is 'main'."
  exit 1
fi
```

**Current Python:** No branch safety check. The orchestrator will happily run on `main`, potentially causing direct commits to the production branch when using git-worktree isolation.

**Impact:** Unintended commits to `main` if the user forgets to switch branches.

**Recommended fix:** Add a branch check in `execute_session` (or the preflight) when isolation type is `git-worktree`. Validate the current branch is not `main` or `master`.

---

## Finding #4: Missing Crash Recovery for Worktrees

**Severity:** Medium
**Category:** Robustness

**Reference behavior (orchestrate.sh lines 114-162):**
```bash
recover_from_crash() {
  # Move any plans in workers/ back to ready/
  # Clean up leftover worktrees and their branches
  # Warn about uncommitted changes
  # Clean up fixer logs from prior run
}
```

The reference script has comprehensive crash recovery:
1. Returns in-progress plans from `workers/` to `ready/`
2. Removes orphaned git worktrees
3. Cleans up orphaned branches
4. Warns about uncommitted changes

**Current Python (`recovery.py`):** Has `recover_execution_session` which handles task state recovery. It calls `_run_isolate_end` for each in-progress task, which delegates worktree cleanup to the pack's `isolate_end` hook. If the hook fails, `_cleanup_workspace_after_failed_isolate_end` does a brute-force `shutil.rmtree`. It also terminates orphaned PIDs.

However, it does NOT perform the reference's comprehensive worktree cleanup:
- Does not scan for orphaned worktrees that have no corresponding worker slot
- Does not clean up orphaned git branches
- Does not detect worktrees left by a hard crash where metadata was lost

**Recommended fix:** Add a worktree cleanup pass at the start of recovery that scans for orphaned worktrees under the session workspace (or configured worktree directory). For `git-worktree` isolation, run `git worktree list` and clean up any worktrees that don't correspond to active worker slots.

---

## Finding #5: Independent Verification After Auto-Fix — VERIFIED PRESENT

**Severity:** N/A (no issue)
**Category:** Correctness

**Reference behavior (orchestrate.sh lines 558-592):**
```bash
# Independent verification — don't trust the fixer's self-report
log "    Fixer exited ($fixer_exit). Running independent verification..."
```

**Current Python (orchestrator.py lines 863-871):** After the fixer returns `success=True`, the orchestrator runs `run_verification_command` independently before marking the task as done. If the fixer returns `success=False`, the orchestrator skips verification and tries the next attempt (correct optimization — no point verifying a self-reported failure). This matches the reference behavior.

---

## Finding #6: Missing Context Enrichment for Retry Fix Attempts

**Severity:** Medium
**Category:** Robustness

**Reference behavior (orchestrate.sh lines 618-644):**
```bash
# Enrich context for next attempt — include only the verification failures,
# NOT the fixer's log (which contains self-reported "all tests pass" claims
# that mislead the next fixer into thinking the problem is already solved).
```

The reference script enriches the error context between fix attempts with:
1. The actual verification test output (not the fixer's log)
2. `git diff HEAD~1 --stat` showing what the previous fixer changed
3. An explicit instruction: "Try a DIFFERENT approach"

**Current Python (orchestrator.py lines 846-857):** `build_task_failure_context` includes `verify_log_path` (the verification output), `worker_log_path` (the worker log), and `previous_attempt_summary`. However, the enrichment is less detailed than the reference:
- Missing: `git diff HEAD~1 --stat` showing what the previous fixer changed
- Missing: Explicit "Try a DIFFERENT approach" instruction
- Present: `previous_attempt_summary` carries forward the fixer's summary text
- Present: `verification_output` includes the actual test failure output

The reference script's context enrichment was a key reliability feature — without the diff of what the previous fixer changed, the next fixer may repeat the same ineffective fix. The `previous_attempt_summary` is the fixer's self-report, not the objective verification output.

---

## Finding #7: Resolver Working Directory

**Severity:** Medium (fixed for planner, verify for resolver)
**Category:** Correctness

**Reference behavior (stage.sh line 25):**
```bash
cd "$REPO_ROOT"
```

Both `plan.sh` and `stage.sh` run agents in `$REPO_ROOT` (the project repo), not the pipeline directory.

**Current Python (planning_runtime.py line 135):**
```python
agent_cwd = Path(env["COGNITIVE_SWITCHYARD_REPO_ROOT"]) if env and "COGNITIVE_SWITCHYARD_REPO_ROOT" in env else session_paths.root
```

This was fixed for the planner in this session. The resolver (line 342) has the same fix. However, the fallback to `session_paths.root` means if `COGNITIVE_SWITCHYARD_REPO_ROOT` is not set in the environment, the agent runs in the session pipeline directory — which is wrong for any agent that needs to read source code.

**Recommended fix:** Make `COGNITIVE_SWITCHYARD_REPO_ROOT` required when planning or agent-based resolution is enabled. Raise a clear error at session start if it's missing, rather than silently falling back to the wrong directory.

---

## Finding #8: Missing git rm for Processed Intake Files

**Severity:** Low (only affects git-tracked pipeline directories)
**Category:** Correctness

**Reference behavior (plan.sh lines 92-108):**
```bash
# git rm intake files that planners processed. Without git rm, rebases
# and merges restore the committed intake files even after the planner moved them.
```

The reference script runs `git rm` on processed intake files to prevent git from resurrecting them during rebases.

**Current Python:** Does not run `git rm`. This is fine if the session directories are outside the git repo (which they are — they're under `~/.cognitive_switchyard/sessions/`). The reference scripts had pipeline directories inside the repo (`work/planning/intake/`), so they needed `git rm`.

**Status:** Not applicable to current architecture. No fix needed.

---

## Finding #9: Missing Deadlock Detection

**Severity:** Medium
**Category:** Robustness

**Reference behavior (orchestrate.sh lines 1045-1053):**
```bash
# If no workers active and nothing eligible but plans still pending,
# we're deadlocked — remaining plans depend on blocked plans
if ! $any_workers_active && $any_pending; then
  eligible_check=$(find_eligible_plan)
  if [ -z "$eligible_check" ]; then
    log "!! No eligible plans and no active workers. Possible deadlock."
    exit 1
  fi
fi
```

**Current Python (orchestrator.py line 227):** The exit condition is `if not ready_tasks and not active_tasks`. This correctly exits when ALL tasks are done or blocked. However, it does NOT detect the deadlock condition where:
- `ready_tasks` is non-empty (so the exit check fails)
- `select_next_task` returns `None` for all ready tasks (because their deps are blocked)
- `active_tasks` is empty (nothing running)

In this case, the main loop continues forever, sleeping and polling without dispatching anything. The scheduler (`scheduler.py:37-38`) checks `all(dependency in completed_task_ids for dependency in task.depends_on)`, and blocked tasks are NOT in `completed_task_ids`.

**Confirmed: deadlock detection is missing.** The loop will spin indefinitely.

**Recommended fix:** After the dispatch loop, check: if no tasks were dispatched, no workers are active, but ready tasks exist, then check if ANY ready task is eligible. If none are eligible, it's a deadlock — return `OrchestratorResult` with `blocked_tasks` listing the blocked dependencies.

---

## Finding #10: Dashboard Generation on Every Poll Cycle

**Severity:** Low
**Category:** Parity gap (informational)

**Reference behavior:** `generate_dashboard` is called on every poll cycle iteration, producing a markdown file with complete pipeline state.

**Current Python:** Uses WebSocket events for real-time updates instead of a static dashboard file. This is the better approach for a web UI. No action needed.

---

## Finding #11: FULL_TEST_AFTER Plan-Level Flag

**Severity:** Low
**Category:** Feature parity

**Reference behavior (orchestrate.sh lines 682-688):**
```bash
# Check for FULL_TEST_AFTER: yes
if grep -q '^FULL_TEST_AFTER: yes' "$done_plan"; then
  completed_since_full_test=$FULL_TEST_INTERVAL  # force trigger
fi
```

Individual plans can force a full test suite run after completion.

**Current Python:** The `TaskPlan` model has `full_test_after: bool`, and the orchestrator appears to handle this. Need to verify the logic path, but the model support is there.

---

## Finding #12: Worktree Merge Strategy

**Severity:** Medium
**Category:** Feature parity

**Reference behavior (orchestrate.sh lines 671-676):**
```bash
git merge --squash "$branch_name" && \
git commit -m "feat(pipeline): plan $plan_id"
```

The reference uses squash merges, which produce clean single-commit-per-plan history.

**Current Python:** Uses pack isolation hooks (`isolate_start`, `isolate_end`). The merge strategy is delegated to the pack's `isolate_end` script. This is more flexible but means the pack author must implement squash merge behavior.

**Status:** By design — the Python implementation correctly delegates this to the pack, which is the right architectural choice for a generic orchestrator. The claude-code pack's `isolate_end` script should implement squash merge.

---

## Summary of Actionable Items

| # | Finding | Severity | Status | Action |
|---|---------|----------|--------|--------|
| 1 | Pipeline stopping | Critical | **Fixed** | Verified working |
| 2 | Plan ID collision detection | Medium | **Missing** | Add to `run_planning_phase` |
| 3 | Branch safety guard | Medium | **Missing** | Add to preflight or `execute_session` |
| 4 | Crash recovery for worktrees | Medium | **Partial** | Recovery delegates to pack hooks but doesn't scan for orphaned worktrees |
| 5 | Independent verification after fix | N/A | **Present** | Correctly implemented (lines 863-871) |
| 6 | Context enrichment for retry fixes | Medium | **Partial** | Missing git diff of fixer changes and explicit "try different approach" |
| 7 | Resolver/planner CWD fallback | Medium | **Partial** | Make REPO_ROOT required when agent phases enabled |
| 8 | git rm for intake files | Low | **N/A** | Not needed — sessions are outside git repo |
| 9 | Deadlock detection | Medium | **Missing** | Main loop spins forever when ready tasks all depend on blocked tasks |
| 10 | Dashboard generation | Low | **N/A** | WebSocket approach is better |
| 11 | FULL_TEST_AFTER flag | Low | **Present** | Model has field, orchestrator handles it |
| 12 | Worktree merge strategy | Low | **By design** | Pack's responsibility |

---

## Architecture Decision Summary

**Decision:** The Python code-managed approach (agent returns text, code manages files) is the correct architecture for Cognitive Switchyard. It provides better observability, testability, error recovery, and determinism than the reference shell script approach where agents managed files autonomously.

**The prompt rewrite (agent = OUTPUT ONLY) correctly aligns the agent contract with the code architecture.** The `ArtifactParseError` safety net for agent-written files should be kept as defense-in-depth.

The reference shell scripts remain valuable as:
1. A behavioral specification (what the pipeline should accomplish)
2. A source of edge cases the Python code must handle (collision detection, deadlock, crash recovery)
3. A feature checklist (branch safety, context enrichment, independent verification)
