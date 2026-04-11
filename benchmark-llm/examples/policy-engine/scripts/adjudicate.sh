#!/usr/bin/env bash
set -euo pipefail

cd "$BENCH_WORKSPACE"

source .venv/bin/activate

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROMPT_PATH="$BENCH_RUN_DIR/adjudication_prompt.txt"
python "$BENCH_BENCHMARK_DIR/scripts/render_adjudication_prompt.py" \
  "$BENCH_BENCHMARK_DIR" \
  "$BENCH_RUN_DIR" \
  "$BENCH_MODEL" \
  > "$PROMPT_PATH"

ADJUDICATOR_MODEL="${BENCH_POLICY_ENGINE_ADJUDICATOR_MODEL:-$BENCH_MODEL}"
ADJUDICATOR_BIN="${BENCH_POLICY_ENGINE_ADJUDICATOR_BIN:-cx}"
EVENTS_PATH="$BENCH_RUN_DIR/adjudication_events.jsonl"

# Claude Code alternative via your `cc` wrapper:
# "$ADJUDICATOR_BIN" --print \
#   --model "$ADJUDICATOR_MODEL" \
#   --output-format json \
#   "$(cat "$PROMPT_PATH")" | tee "$BENCH_RUN_DIR/claude_adjudication.json"
# python "$SCRIPT_DIR/harness_metrics.py" \
#   extract-claude-metrics \
#   "$BENCH_RUN_DIR/claude_adjudication.json" \
#   > "$BENCH_COMMAND_METRICS_PATH" 2>/dev/null || true
#
"$ADJUDICATOR_BIN" exec \
  --json \
  -m "$ADJUDICATOR_MODEL" \
  -o "$BENCH_RUN_DIR/adjudication.json" \
  - < "$PROMPT_PATH" | tee "$EVENTS_PATH"

python "$SCRIPT_DIR/harness_metrics.py" \
  extract-codex-metrics \
  "$EVENTS_PATH" \
  > "$BENCH_COMMAND_METRICS_PATH" 2>/dev/null || true

python "$BENCH_BENCHMARK_DIR/scripts/render_report.py" \
  "$BENCH_RUN_DIR" \
  "$BENCH_BENCHMARK_DIR/report_template.md"
