# Built-In Claude Code Pack

The bundled `claude-code` pack is the reference agent-backed pack shipped with Cognitive Switchyard. After bootstrap, the runtime copy lives at `~/.cognitive_switchyard/packs/claude-code`.

## What It Uses

- planning: Claude agent prompt
- resolution: Claude agent prompt
- execution: Claude-backed worker launcher
- verification: enabled
- auto-fix: enabled
- isolation: `git-worktree`

## Prerequisites

Validate the runtime copy before use:

```bash
./switchyard validate-pack ~/.cognitive_switchyard/packs/claude-code
```

Typical operator prerequisites:

- Claude CLI available in `PATH`
- authenticated Claude session
- a valid repository root for git-worktree isolation (when a session branch is selected, `COGNITIVE_SWITCHYARD_REPO_ROOT` will point to the session worktree, not the original repo)

## Prompt Files

The pack includes:

- `prompts/system.md`
- `prompts/planner.md`
- `prompts/resolver.md`
- `prompts/worker.md`
- `prompts/fixer.md`

## Customization

Edit the runtime copy, not the bundled source copy:

```bash
~/.cognitive_switchyard/packs/claude-code/
```

Common customization points:

- prompt wording
- prerequisite checks
- worker/verification script behavior

If you need a clean baseline again:

```bash
./switchyard reset-pack claude-code
```
