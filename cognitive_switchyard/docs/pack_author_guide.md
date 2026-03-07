# Pack Author Guide

## Overview

A pack tells Cognitive Switchyard how to run a workload. Packs live under
`packs/<name>/` and contain:

- `pack.yaml`
- `scripts/`
- `templates/`
- optional `prompts/`

## Minimal Pack

At minimum, define an execution phase in `pack.yaml` and provide an executable
`scripts/execute` file.

```yaml
name: my-pack
description: Example workload
version: "0.1.0"

phases:
  planning:
    enabled: false
  resolution:
    enabled: false
    executor: passthrough
  execution:
    executor: shell
    command: scripts/execute
    max_workers: 1
```

## Recommended Workflow

1. Run `.venv/bin/python -m cognitive_switchyard init-pack <name>`
2. Implement `scripts/execute`
3. Add any prerequisite checks in `pack.yaml`
4. Validate with `.venv/bin/python -m cognitive_switchyard validate-pack packs/<name>`
5. Add tests for any pack-specific planner, resolver, or fixer scripts

## Script Conventions

- Use a shebang and make scripts executable
- Write task status to a `.status` file next to the plan file
- Emit progress markers with `##PROGRESS##` when long-running
- Exit non-zero on failure

## Planning and Resolution

- Script-backed planning receives: `claimed_item staging_dir review_dir`
- Script-backed resolution receives: `staging_dir ready_dir resolution_json_path`
- Auto-fix scripts receive: `context_path session_dir task_id source_dir`

## Agent Prompt Safety

If a pack uses `agent` executors, keep prompt files runtime-neutral:

- Do not hardcode absolute repository paths
- Do not copy legacy `work/planning/...` or `work/execution/...` paths from another system
- Use the orchestrator-injected `## SWITCHYARD_CONTEXT` values as the source of truth for session paths
- Treat prompts as reusable templates, not repo-specific transcripts

`validate-pack` checks built-in prompt files for known dangerous path patterns.
