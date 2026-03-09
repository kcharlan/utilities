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

1. SAFETY AND BEHAVIORAL CONTRACTS ALWAYS GET THEIR OWN PHASES.
   After identifying the structural phases (models, scheduler, orchestrator,
   etc.), do a second pass over the design doc looking specifically for:
   - Conditional behavior (if X then Y, else Z) — test BOTH branches
   - Distrust/adversarial properties (don't trust output from X, verify
     independently) — test that trusting X alone is insufficient
   - Cleanup/teardown that varies by status — test each status value
   - Retry loops with bounded attempts — test exhaustion and each
     intermediate state (first attempt, retry with enriched context,
     final exhaustion)
   - Features that a component defines but another component must consume
     (config fields, hooks, frontmatter keys) — test the full wiring
   These ALWAYS get their own dedicated phase with their own acceptance
   tests — never combined with the structural phase that builds the
   mechanism. The structural phase builds the auto-fix loop; a separate
   phase tests that the loop's behavioral guarantees hold. This is
   non-negotiable even if the structural phase "seems small enough."
   The reason: when structural and safety tests share a phase, generators
   write tests for the easy structural parts and skip the hard behavioral
   contracts.

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

   Specific anti-patterns to avoid:
   - `assert result.returncode == 0` without checking what the script
     actually did (files created, git state changed, etc.)
   - `assert mock.called_with(correct_args)` without checking the
     effect of the call
   - Testing that a function was invoked but not testing the state
     after the function completed

6. EVERY BEHAVIORAL STATEMENT IN A SPEC REQUIRES A TEST.
   If a spec section describes a behavior in prose ("the orchestrator
   re-runs verification independently", "the second attempt receives
   enriched context"), there MUST be a test that exercises that exact
   behavior. Prose is not coverage — only executable assertions are.
   Before finalizing a phase, re-read its spec section line by line.
   For every sentence that describes what the code DOES (not what it IS),
   ask: "which test function verifies this?" If the answer is "none,"
   write one.

7. TEST RESOURCE LIFECYCLE END-TO-END.
   When the design doc describes resources that are created, used, and
   cleaned up (workspaces, temporary directories, branches, subprocesses,
   lock files), write tests for the FULL lifecycle — not just creation.
   Specifically:
   - Creation: resource is created correctly
   - Cleanup on success: resource is cleaned up after successful use
   - Preservation on failure: resource is preserved (or cleaned up
     differently) after failed use
   - Orphan recovery: if the process crashes mid-lifecycle, the
     recovery path handles the abandoned resource correctly
   If the design doc says "on success, merge and delete" and "on failure,
   preserve for debugging," those are TWO separate tests. If it says
   "recovery cleans up orphaned resources," that is a THIRD test.

   This includes resources managed by hooks and scripts, not just
   in-process objects. If a hook creates a git worktree, temporary
   directory, or branch, the test must verify the EXTERNAL STATE
   (directory exists/doesn't exist, branch was merged, files are
   present). Testing that the hook was called is insufficient —
   test what the hook PRODUCED.

8. TEST MULTIPLICITY AND STATE ACCUMULATION.
   When the design doc describes 1→N relationships (one input producing
   multiple outputs, one event triggering multiple actions) or retry
   loops where each attempt receives different context:
   - 1→N: test that N outputs are actually produced from 1 input, not
     just that the mechanism exists for handling multiple outputs.
     PIPELINE STAGES ARE COMMON 1→N PATTERNS: when a pipeline stage
     takes input A and produces output(s) in a directory, test that
     ONE input can produce MULTIPLE outputs. A test that feeds N
     inputs and checks N outputs only proves 1:1 — it does not prove
     the stage can fan out. Write a test with 1 input that produces
     2+ outputs and verify all outputs flow through downstream stages.
   - Concurrency: when the design doc specifies a "max_instances" or
     "max_workers" capacity > 1 for a stage, test with multiple items
     eligible simultaneously and verify concurrent execution actually
     occurs (e.g., overlapping start/end timestamps, multiple processes
     alive at the same time).
   - Retry enrichment: if attempt N+1 receives more context than
     attempt N (previous results, additional diagnostics), write a
     test that asserts the CONTENT of the enriched context, not just
     that the retry happened. A test that only checks "attempt count
     == 2" misses whether the second attempt was meaningfully
     different from the first.
   - Counter/interval triggers: if something fires "every N events,"
     test both that it fires at N and does NOT fire before N. Test
     that the counter resets correctly after firing.

9. TEST CONSUMER BEHAVIOR FOR EVERY DECLARED TRIGGER.
   When the design doc defines a configuration key, frontmatter field,
   or flag that changes system behavior ("when X is true, do Y;
   otherwise do Z"), write tests for BOTH values — not just the
   existence of the field in the data model. The structural phase
   may define the field and parse it, but a behavioral phase must
   test that the system actually ACTS on it. Specifically:
   - Test with the trigger active (flag=true, field present, threshold
     reached) and verify the triggered behavior occurs
   - Test with the trigger inactive (flag=false, field absent, threshold
     not reached) and verify the triggered behavior does NOT occur
   These are distinct from Rule 3's failure-mode tests. Rule 3 covers
   "what if the input is bad?" Rule 9 covers "what if the input is
   valid but the feature toggle is off?"

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

SELF-AUDIT (mandatory final step):

After generating all phases, perform a cross-reference audit. This is
a two-pass process:

PASS 1: EXHAUSTIVE ENUMERATION. Re-read the design doc section by
section, front to back. For EACH section, extract every behavioral
statement using these categories as a checklist:

a) ACTIONS: What does the system DO? Look for action verbs: creates,
   moves, deletes, merges, kills, validates, broadcasts, copies,
   cleans up, dispatches, collects, parses, writes. Each verb phrase
   is a candidate requirement.
b) CONDITIONALS: Where does behavior BRANCH? Look for: if/else,
   when/unless, on success/on failure, status-dependent, enabled/
   disabled. Each branch is a separate requirement — the true-branch
   and false-branch each need a test.
c) RESOURCE LIFECYCLES: What resources are CREATED that must later be
   CLEANED UP? (workspaces, temporary directories, branches, lock
   files, subprocesses). For each: test creation, test cleanup-on-
   success, test preservation-on-failure, test orphan recovery.
d) CROSS-COMPONENT WIRING: What does one component DEFINE that another
   component must CONSUME? (config fields, frontmatter keys, hook
   arguments, file formats). Test that the consumer actually reads
   and acts on what the producer writes. Pay special attention to
   frontmatter fields and config flags that change orchestrator
   behavior — if a field is parsed in a data model phase but
   triggers behavior in the orchestrator, BOTH the parsing AND the
   triggered behavior need tests (usually in different phases).
   For each field/flag identified: enumerate it as TWO requirements
   — one for "field present/active" and one for "field absent/
   inactive." Both must map to test functions. A field mentioned in
   the spec description but lacking a dedicated test is a gap.
e) MULTIPLICITY: Where can one input produce MULTIPLE outputs, or one
   event trigger multiple actions? Test the N case, not just the 1
   case. If a design doc says a component "can produce multiple
   outputs from a single input," that 1→N relationship must have a
   test showing N > 1 outputs from 1 input. PIPELINE STAGES are
   the most common source of missed 1→N relationships: when stage
   A processes an item and writes output(s) to a directory that
   stage B reads, test that stage A can write MULTIPLE outputs from
   ONE input and that all of them flow through stage B. A test
   that feeds N inputs and gets N outputs proves 1:1, not 1→N.
   Also test concurrent processing when the design doc specifies
   max_instances > 1 — verify overlapping execution actually occurs.
f) BOUNDED LOOPS: Where are there retry/attempt loops with limits?
   Test the intermediate states (what context does attempt 2 get
   that attempt 1 didn't?) and the terminal state (exhaustion).
g) HOOKS AND SCRIPTS THAT PRODUCE EXTERNAL STATE: If the design doc
   describes hooks or scripts that create, modify, or destroy
   external resources (directories, branches, merged commits,
   processes), enumerate each hook's effects per status. For each
   hook that behaves differently based on a status argument (e.g.,
   "done" vs "blocked"), list each variant as a separate
   requirement. Also enumerate any safety guards that prevent hooks
   from running in dangerous conditions (e.g., refusing to operate
   on protected branches).

Do NOT skip any section of the design doc. Do NOT rely on memory of
what you already covered in the phase specs — read the design doc
fresh and enumerate independently.

PASS 2: MAP TO TESTS. For each enumerated requirement, identify the
specific test function that covers it. Present the audit as a table:

  | Design doc requirement | Section | Phase | Test function(s) |
  |------------------------|---------|-------|-------------------|
  | Fixer verified independently | 3.6 | phase_07 | test_autofix_... |
  | ...                    | ...     | ...   | ...               |

Rules for the audit:
- If a requirement has no test: STOP. Add a test to the appropriate
  phase or create a new phase. Do not finish without full coverage.
- If a requirement is covered only by a mechanism test (checks args,
  not outcomes): flag it and rewrite the test to check outcomes.
- LIFECYCLE CROSS-CHECK: After completing the audit table, scan it
  for every resource lifecycle from category (c) and every hook from
  category (g). For each resource/hook, verify that the table contains
  ALL of: creation test, cleanup-on-success test, preservation-on-
  failure test, and orphan recovery test. If any lifecycle phase is
  missing from the table, STOP and add the test. This is the most
  commonly missed category — generators frequently test creation and
  recovery but forget to test the normal success-path cleanup and
  the normal failure-path preservation.
- TRIGGER-CONSUMER CROSS-CHECK: After completing the audit table,
  scan it for every field/flag from category (d). For each trigger
  field, verify the table contains tests for BOTH the active and
  inactive cases. If a field appears only in a spec description
  ("the orchestrator checks X") but has no dedicated test function,
  STOP and add the test. Merely mentioning a trigger in a spec
  paragraph is not coverage — only test functions count.
- MULTIPLICITY CROSS-CHECK: After completing the audit table, scan
  for every pipeline stage from category (e). For each stage that
  can fan out (1→N), verify a test exists with 1 input producing
  N > 1 outputs. Tests that feed N inputs and check N outputs only
  prove 1:1 — they do not satisfy this check.
- The audit table must appear at the bottom of the STATUS file so
  the human reviewer can verify coverage at a glance.
- Behavioral requirements include: anything the design doc says the
  system DOES, MUST do, MUST NOT do, or does conditionally. Structural
  definitions (data models, field lists, file formats) do not need
  individual audit entries — they are covered by structural phase tests.
- BEHAVIORAL REQUIREMENTS CANNOT BE DEFERRED. The "Follow-on
  sub-projects" section is for DELIVERABLES only — packs, UI views,
  documentation, CLI tools, external integrations. If the design doc
  says the system must DO something (verify independently, enrich
  context on retry, enforce a timeout, broadcast a warning, clean up
  on failure), that behavior MUST have a test in a phase — even if
  the deliverable that ultimately uses it is deferred. For example:
  auto-fix independent verification is a behavioral requirement that
  must be tested in a phase, even though the claude-code pack that
  exercises it in production is a deferred deliverable. Do NOT create
  a "Deferred requirements" subsection in the audit table. Every row
  in the audit table must map to a test function — no exceptions.

TOKEN BUDGET NOTE: Safety/behavioral contract phases (phases that test
cross-cutting behaviors rather than building new modules) may exceed
the normal test token budget if needed — complex behavioral tests
require more setup code (custom packs, threaded orchestrator runs,
timing instrumentation). However, if a single phase's test section
exceeds ~2000 tokens, consider splitting it into two phases rather
than creating one oversized phase that will overwhelm the implementer.

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

3. ONLY defer deliverables, never behavioral requirements. A deferred
   follow-on is a thing to BUILD (a pack, a UI, a CLI tool, a doc).
   Behavioral contracts described in the design doc (timeout enforcement,
   auto-fix verification, constraint checking, recovery guarantees) must
   be tested in the core phases even if the deliverable that exercises
   them in production is deferred.

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
