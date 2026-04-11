# policy-engine repo-task example

This example adapts the policy-engine evaluation package into `benchmark-llm`'s repo-task shape.

It is meant to be both runnable and readable:

- the framework owns worktree creation, artifact capture, and structured command provenance
- the benchmark package owns repo prep, model invocation, deterministic validation, model-based adjudication, and the benchmark-specific scorecard

## Required environment

Point the benchmark at the repo you want to evaluate:

```bash
export BENCH_POLICY_ENGINE_SOURCE_REPO=/absolute/path/to/policy-engine
```

The included invocation script is wired for `opencode`:

```bash
bench run examples/policy-engine -m openrouter/qwen/qwen3.6-plus
```

For repeated benchmark sweeps, you can use a model list file instead:

```bash
bench run examples/policy-engine -m @models.txt
```

By default the adjudication step uses `cx` (your `codex` wrapper), but it is a separate shell step and can use the same or a different model:

```bash
export BENCH_POLICY_ENGINE_ADJUDICATOR_MODEL=openrouter/gpt-5
bench run examples/policy-engine -m openrouter/qwen/qwen3.6-plus
```

The default script invokes Codex non-interactively with `exec` and feeds the adjudication prompt on stdin. To use a different CLI binary for adjudication, set `BENCH_POLICY_ENGINE_ADJUDICATOR_BIN` or edit `scripts/adjudicate.sh`. The framework preserves the worktree and branch either way because adjudication is just another benchmark-owned step running after validation.

`scripts/adjudicate.sh` also includes a commented Claude Code example for your `cc` wrapper. That path uses Claude's non-interactive `--print` mode with JSON output, while the active default remains `cx exec`.

The model execution step itself receives a scrubbed environment with neutral task inputs such as `MODEL_ID`, `WORKSPACE_ROOT`, and `TASK_PROMPT_PATH`. Framework-owned `BENCH_*` variables stay available to the non-model steps like prepare, validate, and adjudicate.

If the `opencode` wrapper can recover usage data, it can write a JSON payload to `TASK_METRICS_PATH` during the execute step. The same pattern works for adjudication or validation steps through `BENCH_COMMAND_METRICS_PATH`.

## Layout

```text
policy-engine/
  bench.yaml
  prompt.txt
  report_template.md
  visible/
  hidden/
  scripts/
```

`report_template.md` is a reusable scorecard template derived from the original evaluation sheet, but with placeholders instead of baked-in results.

The manifest uses the recommended repo-task shape:

- `executor.command` is the authoritative model invocation
- the execute step references it with `use_executor: true`
- named steps become the phase names stored in `commands.jsonl`
- validation is deterministic and writes `validation_summary.json`
- adjudication is a second CLI/model invocation that turns those artifacts into `score.json` and `report.md`
