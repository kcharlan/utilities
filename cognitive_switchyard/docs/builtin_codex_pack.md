# Built-In Codex Pack

The bundled `codex` pack is the OpenAI Codex CLI runner pack shipped with Cognitive Switchyard. After bootstrap, the runtime copy lives at `~/.cognitive_switchyard/packs/codex`.

## What It Uses

- planning: Claude agent prompt (Anthropic runtime)
- resolution: Claude agent prompt (Anthropic runtime)
- execution: Codex CLI worker launcher (`codex exec`)
- verification: enabled
- auto-fix: enabled (Claude agent)
- isolation: `git-worktree`

## Prerequisites

Validate the runtime copy before use:

```bash
./switchyard validate-pack ~/.cognitive_switchyard/packs/codex
```

Typical operator prerequisites:

- Codex CLI available in `PATH`
- authenticated OpenAI session
- a valid repository root for git-worktree isolation (when a session branch is selected, `COGNITIVE_SWITCHYARD_REPO_ROOT` will point to the session worktree, not the original repo)

## Worker Model

The default worker model is `gpt-5.4`. Override with the `CODEX_WORKER_MODEL` environment variable:

```bash
CODEX_WORKER_MODEL=o3 ./switchyard start --session demo --pack codex
```

## Prompt Files

The pack includes:

- `prompts/system.md`
- `prompts/planner.md`
- `prompts/resolver.md`
- `prompts/worker.md`
- `prompts/fixer.md`

Planning, resolution, and auto-fix phases use the Anthropic Claude runtime regardless of the execution agent. Only the execution phase invokes the Codex CLI.

## Customization

Edit the runtime copy, not the bundled source copy:

```bash
~/.cognitive_switchyard/packs/codex/
```

Common customization points:

- prompt wording
- prerequisite checks
- worker/verification script behavior
- default model (`CODEX_WORKER_MODEL`)

If you need a clean baseline again:

```bash
./switchyard reset-pack codex
```
