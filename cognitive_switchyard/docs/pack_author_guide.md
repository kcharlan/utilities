# Pack Author Guide

Custom packs live under `~/.cognitive_switchyard/packs/<pack-name>`. Cognitive Switchyard loads only runtime packs from that directory, including built-in packs after bootstrap sync.

## Quick Start

Create a scaffold:

```bash
./switchyard init-pack my-pack
./switchyard validate-pack ~/.cognitive_switchyard/packs/my-pack
```

The scaffold creates:

- `pack.yaml`
- `README.md`
- `prompts/`
- `scripts/`
- `templates/`

## Required Contract

`pack.yaml` must use the canonical `cognitive_switchyard` pack schema:

- `name`: kebab-case identifier
- `description`: human-readable summary
- `version`: semver
- `phases.execution`: always enabled
- `isolation.type`: `git-worktree`, `temp-directory`, or `none`

Optional phases and features:

- `phases.planning`
- `phases.resolution`
- `phases.verification`
- `auto_fix`
- `prerequisites`
- `timeouts`
- `status`

## Hooks

Hooks are invoked by the orchestrator, not by the pack itself.

- `scripts/execute`: required for `executor: shell`
- `scripts/preflight`: optional conventional hook
- `scripts/isolate_start`: optional conventional hook
- `scripts/isolate_end`: optional conventional hook
- `scripts/resolve`: optional conventional hook when resolution uses `script`

Rules:

- Hook files must stay inside the pack root.
- Hook files must be executable.
- Text hook files need a shebang.
- `execute` must emit `##PROGRESS##` lines and write a `.status` sidecar next to the task plan.

## Validation

Run `validate-pack` before using a pack. It checks:

- manifest/schema errors
- missing referenced files
- non-executable scripts
- text hook scripts without a shebang
- invalid `status.progress_format` regex values

## Idempotency

Pack authors own idempotency for lifecycle hooks:

- `isolate_start` must recreate an interrupted workspace cleanly.
- `isolate_end` must tolerate already-cleaned or already-merged work.
- `execute` is re-run from scratch after interruption; external side effects must be safe to repeat or intentionally accepted.

## Local Iteration

Recommended loop:

```bash
./switchyard validate-pack ~/.cognitive_switchyard/packs/my-pack
./switchyard start --session author-test --pack my-pack
```

If a successful session plan includes `## Operator Actions`, Cognitive Switchyard writes `RELEASE_NOTES.md` into the retained session artifacts. Minimum safe assumption in packet 14: no file is generated when no completed plan contains that section.
