# Workflow Hardening: Resume State (2026-03-08)

## What This Is

We are iteratively hardening `docs/design_to_implementation_workflow.md` — a general-purpose workflow document that tells coding agents how to generate phase specs with acceptance tests from any design doc. The test project is Cognitive Switchyard (design doc at `docs/cognitive_switchyard_design.md`).

## Core Rules (Non-Negotiable)

1. **All changes go into the workflow document**, not into the generator prompt. The prompt at `/tmp/switchyard_generator_prompt.txt` contains ONLY references to the two docs — no project-specific hints.
2. **Changes must be general-purpose**, not project-specific. Rules describe patterns (resource lifecycle, trigger-consumer gaps, 1→N relationships), not specific requirements (squash merge, FULL_TEST_AFTER).
3. **Test using only what's in the document** — no side-channel hints.
4. **Iterate until two consecutive strong outputs (9-10/10)** that are semantically similar.

## Current Prompt (Do Not Modify)

```
Read /Users/kevinharlan/source/utilities/cognitive_switchyard/docs/cognitive_switchyard_design.md.

Then read /Users/kevinharlan/source/utilities/cognitive_switchyard/docs/design_to_implementation_workflow.md for the COMPLETE instructions on how to generate phase specs.

Follow the Step 2 instructions exactly. Generate phase specs with acceptance tests for the Cognitive Switchyard project. Write each phase file to docs/phases/phase_NN_[name].md and create the STATUS file with the self-audit table.
```

Stored at `/tmp/switchyard_generator_prompt.txt`. Recreate if missing.

## How to Run the Generator

```bash
unset CLAUDECODE && cc-opus -p "$(cat /tmp/switchyard_generator_prompt.txt)" --max-turns 50
```

- `cc-opus` is a shell function: `claude --dangerously-skip-permissions --model opus "$@"`
- Must `unset CLAUDECODE` when running from within a Claude Code session
- Output goes to `docs/phases/phase_NN_[name].md` and `docs/phases/STATUS`
- Clean up between runs: `rm docs/phases/phase_*.md docs/phases/STATUS`

## 10 Safety Properties (Audit Checklist)

Score each generated output against these 10 properties derived from the Cognitive Switchyard design doc:

| # | Property | What to look for |
|---|----------|-----------------|
| 1 | Auto-fix independent verification | Test that orchestrator re-runs verify after fixer, not trusting fixer's self-report |
| 2 | Auto-fix context enrichment | Test that attempt N+1 receives MORE content than attempt N (not just that retry happened) |
| 3 | Isolate lifecycle (done=cleanup) | Test that workspace directory is removed after successful task (isolate_end "done") |
| 4 | Isolate lifecycle (blocked=preserve) | Test that workspace directory is preserved after failed task (isolate_end "blocked") |
| 5 | FULL_TEST_AFTER frontmatter trigger | Test that a task with FULL_TEST_AFTER triggers verification regardless of interval counter |
| 6 | Recovery workspace cleanup | Test that orphaned workspaces are handled during crash recovery (force cleanup on isolate_end failure) |
| 7 | Branch guard | Claude-code pack specific. Acceptable to defer to followon_claude_code_pack |
| 8 | Prompt validation | Tests that pack.yaml rejects missing prompts/commands when features are enabled |
| 9 | Planner 1→N / parallelism | Test that one intake item can produce multiple plans, or explicit analysis that the design is 1:1 |
| 10 | Session-level verification | Test that verification runs every N completed tasks and pauses dispatch |

## Score History

| Iteration | Score | Key Changes to Workflow | What Improved | What Remained |
|-----------|-------|------------------------|---------------|---------------|
| 1 (pre-conversation) | 4/10 | None (baseline after user's run) | — | 3,4,5,6,7,9 missing |
| 1 (post rules 7-9 + categories a-f) | 5/10 | Added rules 7,8,9; structured Pass 1 categories a-f | Some timeout/autofix tests appeared | 3,4,5,6,7,9 still missing |
| 1 (post rule 7 strengthen + cat g) | 9/10 | Strengthened Rule 7 for hook external state; added Pass 1 category g | 3,4,5,6 all recovered | Only 9 missing |
| 2 | 7/10 | Strengthened Rule 8 for pipeline stages + concurrency | — | 3,4 regressed (phase reorganization lost tests) |
| 3 | 8/10 | Added lifecycle cross-check rule in audit | 3,4 recovered from rule | 5,9 still missing |
| 4 | 9-10/10 | Added trigger-consumer + multiplicity cross-checks; strengthened cat d,e | 5 recovered; 9 explicitly analyzed (concluded 1:1) | 9 is borderline (informed decision vs gap) |

## Changes Made to Workflow Document (Cumulative)

All changes are in `docs/design_to_implementation_workflow.md`. Key additions:

### Phase Planning Rules (Rules 7-9, after existing Rule 6)

- **Rule 7**: TEST RESOURCE LIFECYCLE END-TO-END — creation, cleanup-on-success, preservation-on-failure, orphan recovery. Includes paragraph about hooks/scripts that produce external state.
- **Rule 8**: TEST MULTIPLICITY AND STATE ACCUMULATION — 1→N fan-out (including pipeline stage fan-out and concurrency), retry enrichment (content not count), counter/interval triggers.
- **Rule 9**: TEST CONSUMER BEHAVIOR FOR EVERY DECLARED TRIGGER — both values of every flag/field, not just existence.

### Pass 1 Categories (a-g)

- Categories a-f: ACTIONS, CONDITIONALS, RESOURCE LIFECYCLES, CROSS-COMPONENT WIRING (strengthened to require two requirements per field: active + inactive), MULTIPLICITY (strengthened for pipeline stages), BOUNDED LOOPS.
- **Category g** (new): HOOKS AND SCRIPTS THAT PRODUCE EXTERNAL STATE — enumerate each hook's effects per status, including safety guards.

### Pass 2 Audit Rules (three new cross-checks)

- **LIFECYCLE CROSS-CHECK**: Scan for every resource/hook, verify all 4 lifecycle phases have tests.
- **TRIGGER-CONSUMER CROSS-CHECK**: Scan for every field/flag, verify both active and inactive tests exist. Spec mentions don't count — only test functions.
- **MULTIPLICITY CROSS-CHECK**: Scan for every pipeline stage, verify 1→N test exists (not just 1:1).

## What Remains

### Option A: Declare Victory
Iterations 1 and 4 both scored 9+/10. Property #9 is the only persistent gap, and iteration 4 handled it with an explicit analysis ("No 1→N fan-out in pipeline design"). This could be considered two consecutive strong, semantically similar outputs.

### Option B: Continue Iterating
Run iterations 5 and 6. If both score 9+/10, that's unambiguous. The risk is that the generator will occasionally reorganize phases and regress (as iteration 2 showed), but the cross-check rules now catch most regressions.

### Option C: Investigate Property #9 Deeper
Check the design doc section 3.2 to determine whether the planner truly supports 1→N or if it's 1:1. If 1:1 is correct, property #9 should be removed from the checklist. If 1→N, the workflow needs a stronger signal.

## File Inventory

| File | Purpose |
|------|---------|
| `docs/design_to_implementation_workflow.md` | **Primary deliverable** — the workflow being hardened |
| `docs/cognitive_switchyard_design.md` | Test project's design doc |
| `docs/phases/phase_*.md` | Generated phase specs (from latest iteration; clean before each run) |
| `docs/phases/STATUS` | Generated self-audit + cross-check tables |
| `/tmp/switchyard_generator_prompt.txt` | Clean generator prompt (recreate if missing) |
| `docs/workflow_hardening_resume.md` | This file |

## Branch

Working on branch `cognitive-switchyard`. Nothing has been committed during this session — all changes are unstaged.
