Built-in runner pack for OpenAI Codex CLI driven planning, resolution, execution,
verification, and auto-fix.

Prerequisites:
- `codex` must be installed and authenticated on `PATH`.
- `git` must be available on `PATH`.
- For git-worktree isolation, set `COGNITIVE_SWITCHYARD_REPO_ROOT` to the
  repository root that workers should execute inside.

Runtime notes:
- Planning, resolution, and auto-fix use the Anthropic Claude runtime adapter
  (these phases use Claude regardless of the execution agent).
- Execution delegates worker calls to `scripts/execute`, which invokes `codex exec`.
- Verification uses `scripts/verify` through the pack-root environment exported
  by the orchestrator. The built-in verifier runs from the effective target
  directory, reuses the source repo's virtualenv for worktree sessions when
  available, and never falls back to the switchyard bootstrap venv.
- Default worker model is `gpt-5.4` (override with `CODEX_WORKER_MODEL` env var).
