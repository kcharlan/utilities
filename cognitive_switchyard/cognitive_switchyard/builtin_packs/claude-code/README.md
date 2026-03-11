Built-in reference pack for Claude CLI driven planning, resolution, execution,
verification, and auto-fix.

Prerequisites:
- `claude` must be installed and authenticated on `PATH`.
- `git` must be available on `PATH`.
- For git-worktree isolation, set `COGNITIVE_SWITCHYARD_REPO_ROOT` to the
  repository root that workers should execute inside.

Runtime notes:
- Planning, resolution, and auto-fix use the default Claude runtime adapter.
- Execution remains script-based and delegates the worker call to `scripts/execute`.
- Verification uses `scripts/verify` through the pack-root environment exported
  by the orchestrator.
