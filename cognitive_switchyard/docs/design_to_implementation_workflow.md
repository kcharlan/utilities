# Design-to-Implementation Workflow

A process for taking a design document to implemented, contract-enforced code using coding agents.

## Principles

1. **Executable specifications over prose.** Prose requirements degrade under attention pressure. Pytest assertions don't. If a requirement matters, it has a test.
2. **Small context, fresh sessions.** Each implementation session loads only the design doc + one phase spec. No 45k-token plans competing for attention.
3. **Tests are the contract.** The acceptance tests define what "done" means for each phase. The implementer cannot modify them without justification.

---

## Workflow

### Step 1: Design doc

Create the design document through whatever process works (discussion, iteration, research). This is your existing workflow — no changes needed.

The design doc should cover architecture, key decisions, data flow, and interfaces. It should NOT contain step-by-step implementation instructions. Target: under 25k tokens (~100KB). If it's larger, it probably contains implementation detail that belongs in phase specs.

Output: `docs/[project]_design.md`

### Step 2: Generate phase specs with acceptance tests

**One fresh session.** This replaces the implementation plan entirely.

#### Prompt

```
Read docs/[project]_design.md.

Break this into implementation phases. Each phase should be an independently
buildable unit — something a coding agent can complete in one session without
needing to reference other phases.

For each phase, produce a separate file: docs/phases/phase_NN_[name].md

Each phase file must contain exactly two sections:

## Spec (under 2000 tokens)

What to build, which files to create or modify, key data structures and
interfaces. Be specific about names, signatures, and formats — but don't write
the implementation code. If this phase depends on artifacts from a prior phase,
name the exact files/functions/schemas it consumes.

## Acceptance tests (under 1000 tokens)

Actual runnable pytest code. Every behavioral requirement from the spec section
must have a corresponding test. These tests define the contract — if the test
doesn't check it, it's not required. If it IS required, there MUST be a test.

For safety-critical behaviors (things that must NOT happen, conditional logic,
error handling, adversarial inputs), write the test from the perspective of
"what would go wrong if the implementer got this subtly wrong?" For example:
if cleanup should only run on success, the test calls the function with a
failure status and asserts the artifacts still exist.

Phase planning rules:

1. SAFETY AND BEHAVIORAL CONTRACTS GET THEIR OWN PHASES.
   After identifying the structural phases (models, scheduler, orchestrator,
   etc.), do a second pass over the design doc looking specifically for:
   - Conditional behavior (if X then Y, else Z) — test BOTH branches
   - Distrust/adversarial properties (don't trust output from X, verify
     independently) — test that trusting X alone is insufficient
   - Cleanup/teardown that varies by status — test each status value
   - Retry loops with bounded attempts — test exhaustion
   - Features that a component defines but another component must consume
     (config fields, hooks, frontmatter keys) — test the full wiring
   These MUST have dedicated acceptance tests. If the structural phase is
   already large, create a separate phase for the safety contract tests.

2. EVERY DELIVERABLE IN THE DESIGN DOC IS A REQUIRED PHASE.
   If the design doc specifies a pack, plugin, script, or integration layer,
   it gets its own phase — it is not optional, and it is not part of "the
   orchestrator phase." Packs, CLI tools, and deployment artifacts are
   first-class deliverables, not afterthoughts.

3. ACCEPTANCE TESTS MUST COVER FAILURE MODES.
   For every conditional behavior, write at least two tests:
   - The happy path (expected input → expected output)
   - The failure/edge path (what happens when the condition is false, the
     input is bad, the subprocess fails, the status is "blocked" not "done")
   A test suite that only tests the happy path is incomplete.

4. TEST INTEGRATION WIRING, NOT JUST INTERNAL LOGIC.
   If module A defines a hook and module B must call it, write a test that
   invokes B's code path and asserts A's hook was executed. Config fields
   that are defined but never consumed are dead code — test that they are
   actually read and acted upon.

5. ASSERT OUTCOMES, NOT MECHANISMS.
   Tests must verify the observable end state, not just that the right
   function was called with the right arguments. "The cleanup function
   received the correct status" is a mechanism test — it passes even if
   the caller does something wrong afterward. "The directory still exists
   after a failure" is an outcome test — it verifies what actually matters.
   Every acceptance test should answer: "What would a human check to
   confirm this worked?" Assert that.

General guidelines:
- Target 6-10 phases per project. If you reach 12+ phases, stop — do not
  continue generating phases. Instead, identify natural sub-project boundaries
  (see "Decomposition" below) and present them for approval before proceeding.
- Each phase spec should be completable by reading only the design doc + that
  one phase file. Don't create cross-references between phase files — inline
  what the implementer needs to know.
- The acceptance test section is real code that I will copy into tests/. Use
  tmp_path, monkeypatch, real subprocess calls where appropriate. No mocks for
  things that can be tested directly.
- Order phases so each builds on prior phases' artifacts. Note this in the spec,
  but the implementer will have the actual code from prior phases available —
  they don't need the prior phase doc.

After generating all phase files, create docs/phases/STATUS with:
- One line per phase: `phase_NN_[name]: pending`
- This file tracks implementation progress across sessions.
- If any deliverables from the design doc were intentionally deferred (because
  they require external dependencies, a different runtime, or would push the
  phase count past 10), add a "Follow-on sub-projects" section at the bottom
  of STATUS listing each deferred item with a brief reason:

  # Follow-on sub-projects (not yet phased)
  followon_[name]: deferred — [reason]; design doc needed

  Every deliverable in the design doc must appear in STATUS — either as a
  phase or as a deferred follow-on. Nothing gets silently dropped.
```

#### Review the output

Before executing any phases, read through the phase specs. Focus on the tests:
- Does every MUST/CRITICAL requirement have a test?
- Are the tests specific? (`assert workspace.exists()` is good; `assert result is not None` is worthless)
- Do safety-critical tests check the failure mode, not just the happy path?

### Step 3: Execute each phase

**One fresh session per phase.** Same prompt every time — no editing needed.

#### Prompt (copy-paste this verbatim each time)

```
Read docs/phases/STATUS to find the next pending phase. Read the design doc
referenced at the top of the phase file for project context, then read the
phase spec itself.

Execute this phase using test-driven development:
1. Copy the acceptance tests from the phase doc into the appropriate test
   file(s) under tests/.
2. Run the tests. Confirm they fail.
3. Implement until all tests pass.
4. Run the full test suite (not just this phase's tests) to check for
   regressions against prior phases.
5. Do not modify the acceptance tests unless they have a genuine bug (wrong
   assertion, not a failing test you want to make pass). If you think a test
   is wrong, stop and explain why before changing it.

When done, update docs/phases/STATUS: change this phase's line from "pending"
to "done" and note the date. If you could not complete the phase, change it to
"blocked: <reason>".
```

#### Context budget

| Item | Tokens | Notes |
|------|--------|-------|
| Design doc | ~20k | Orientation and architecture |
| Phase spec | ~3k | What to build + acceptance tests |
| CLAUDE.md chain | ~5k | Repo conventions |
| Agent headroom | ~170k | Implementation, tool calls, iteration |

### Step 4: Post-implementation verification

**One fresh session after all phases are complete.**

#### Prompt

```
Read docs/phases/STATUS — confirm all phases show "done".

Read the design doc and all phase files under docs/phases/.

Run the full test suite. Then for each phase, verify that the acceptance tests
from the phase doc are present in the test suite and passing. Report any
acceptance tests that were modified or deleted during implementation, with a
diff of what changed and whether the change was justified.
```

---

## Phase Status Tracking

The `docs/phases/STATUS` file is the coordination mechanism across sessions. Format:

```
design_doc: docs/cognitive_switchyard_design.md

phase_01_models_config_state: pending
phase_02_pack_loader: pending
phase_03_scheduler: pending
phase_04_worker_manager: pending
phase_05_orchestrator: pending
phase_06_cli_bootstrap_testpack: pending
phase_07_server_api_websocket: pending
phase_08_web_ui: pending
```

After each session, the agent updates the relevant line:

```
phase_01_models_config_state: done 2026-03-08
phase_02_pack_loader: done 2026-03-08
phase_03_scheduler: blocked: need clarification on deadlock handling
phase_04_worker_manager: pending
```

The step 3 prompt reads this file first and picks the next `pending` entry. No manual editing needed between sessions.

---

## Decomposition: When a project exceeds 10 phases

If step 2 produces 12+ phases, the project is too large for a single design-to-implementation cycle. This doesn't mean the project is too ambitious — it means it needs to be decomposed into sub-projects that each go through this workflow independently.

### How to decompose

When the phase generator hits the limit, it should stop and present a decomposition proposal instead of continuing. Use this prompt:

```
The design requires more than 10 implementation phases. Instead of generating
all phases, decompose the project into sub-projects.

Requirements for sub-projects:
- Each sub-project gets its own design doc and its own phase cycle (steps 2-4).
- Sub-projects must have clean, documented interfaces between them. Define the
  exact contract (function signatures, file formats, data schemas, CLI args)
  at each boundary.
- No circular dependencies between sub-projects. Draw the dependency graph
  and confirm it's a DAG.
- Each sub-project should decompose into 4-8 phases.
- Order sub-projects so each can be fully built and tested before the next
  one starts. A sub-project's tests must pass using stubs/fixtures for
  upstream sub-projects that don't exist yet.

Output:
- docs/decomposition.md — the sub-project breakdown, dependency graph,
  and interface contracts
- One design doc per sub-project: docs/[subproject]_design.md

Do NOT generate phase specs yet. Present the decomposition for review first.
```

### Execution order for sub-projects

After approving the decomposition, run each sub-project through the full workflow (steps 2-4) in dependency order. Each sub-project is a complete cycle:

1. Generate phase specs for sub-project A
2. Execute phases for sub-project A
3. Verify sub-project A
4. Generate phase specs for sub-project B (which can now reference A's real code)
5. ...and so on

### What counts as a natural sub-project boundary

Good boundaries:
- **Data layer vs. business logic vs. UI** — classic tier split
- **Core engine vs. plugin/pack system** — the plugin interface is the contract
- **CLI/API surface vs. internals** — the public interface is the contract
- **Independent subsystems** — e.g., "scheduler" and "worker manager" that communicate through a defined protocol

Bad boundaries:
- Splitting a single module's internals across sub-projects
- Boundaries that require shared mutable state
- Boundaries where the interface isn't stable yet (if you can't define the contract, it's not a real boundary)

---

## What this workflow eliminates

| Before | After |
|--------|-------|
| 45k-token implementation plan | ~3k-token phase specs |
| Separate test plan document | Tests embedded in phase spec |
| Prose behavioral contracts | Executable pytest contracts |
| One giant session | One session per phase |
| Post-hoc auditing for missed requirements | Tests enforce requirements mechanically |
| Editing prompts between sessions | Same prompt every time via STATUS file |
| "Be thorough" instructions | Specific failure-mode tests |

## What to watch for

**Weak tests in step 2.** The risk shifts to the phase spec generator writing tests that check "code runs without error" instead of "code behaves correctly under specific conditions." During review, look for:
- Tests that only assert `is not None` or `isinstance`
- Tests that call a function but don't check its side effects
- Missing negative tests (what happens on bad input, failure status, exhausted retries)
- Safety properties tested only on the happy path

**Modified acceptance tests in step 3.** The implementer may change tests to make them pass rather than fixing the code. Step 4 catches this, but you can also grep for it: `git log --all -p -- tests/` and look for test modifications in the same commit as implementation code.

**Phase coupling.** If an implementer in phase 5 needs to modify code from phase 2 to make phase 5 work, that's a sign the phase boundaries were wrong. It's not necessarily a problem — but if it happens repeatedly, revisit the decomposition.

---

## Follow-on Sub-projects

Step 2 may identify deliverables from the design doc that are out of scope for the current phase cycle but are required future work. For example: the core engine is built first with a test-echo pack, and the real claude-code pack is a follow-on sub-project.

### How the phase generator should handle this

The step 2 prompt already says "every deliverable is a required phase." When the generator determines that a deliverable should be a separate sub-project (because it requires external dependencies, a different runtime, or the phase count would exceed 10), it should:

1. List the deferred sub-projects at the bottom of the STATUS file:

```
# Follow-on sub-projects (not yet phased)
followon_claude_code_pack: deferred — requires Claude CLI; design doc needed
followon_ffmpeg_pack: deferred — requires ffmpeg; design doc needed
followon_pack_scaffolding: deferred — init-pack tooling; design doc needed
```

2. NOT silently drop them. If it's in the design doc, it must appear in STATUS.

### Picking up follow-on sub-projects

After the current cycle completes (all phases done, step 4 verification passed), generate design docs for the follow-on sub-projects. Use this prompt:

```
Read docs/phases/STATUS — all core phases should be "done".

Read the entries under "Follow-on sub-projects" in STATUS. For each deferred
sub-project, read the original design doc (docs/[project]_design.md) and the
now-implemented codebase to understand what interfaces exist.

For each follow-on sub-project, produce a focused design doc:
  docs/[subproject]_design.md

Each design doc should:
- Reference the core project's actual interfaces (import paths, function
  signatures, config schemas, hook protocols) as they exist in the code NOW,
  not as the original design doc described them. Read the code to confirm.
- Define what the sub-project adds on top of the core.
- Be self-contained — a phase generator reading only this design doc (plus
  the existing codebase) should be able to produce phase specs.
- Target under 10k tokens.

After writing all design docs, update STATUS to change each entry from
"deferred" to "design_ready" with the path to its design doc:

  followon_claude_code_pack: design_ready — docs/claude_code_pack_design.md

Do NOT generate phase specs yet. Present the design docs for review first.
```

After reviewing the design docs, run each sub-project through the standard cycle:
1. Generate phase specs (step 2) from the sub-project's design doc
2. Execute phases (step 3) — same copy-paste prompt
3. Verify (step 4)

Update STATUS as each sub-project completes:

```
followon_claude_code_pack: done (2026-03-10)
followon_ffmpeg_pack: pending — phases generated, not yet implemented
```

### Pipeline view

The full lifecycle for a large project:

```
Design doc
  → Step 2: Phase specs (core)
    → Step 3: Implement phases (core)
      → Step 4: Verify (core)
        → Follow-on design docs
          → Step 2: Phase specs (sub-project A)
            → Step 3: Implement phases (sub-project A)
              → Step 4: Verify (sub-project A)
          → Step 2: Phase specs (sub-project B)
            → ...
```

Each arrow is a fresh session. STATUS tracks where you are across the entire tree.
