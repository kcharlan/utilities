#!/usr/bin/env bash
set -euo pipefail

MODEL="${MODEL_ID}"
PROMPT="$(cat "$TASK_PROMPT_PATH")"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
EVENTS_PATH="$(mktemp "${TMPDIR:-/tmp}/opencode-events.XXXXXX.jsonl")"
EXPORT_PATH="$(mktemp "${TMPDIR:-/tmp}/opencode-export.XXXXXX.json")"
trap 'rm -f "$EVENTS_PATH" "$EXPORT_PATH"' EXIT

cd "$WORKSPACE_ROOT"

opencode run \
  --format json \
  --model "$MODEL" \
  --title "policy-engine" \
  "$PROMPT" | tee "$EVENTS_PATH"

SESSION_ID="$(
  python "$SCRIPT_DIR/harness_metrics.py" opencode-session-id "$EVENTS_PATH" \
    2>/dev/null || true
)"

if [ -n "$SESSION_ID" ]; then
  opencode export "$SESSION_ID" > "$EXPORT_PATH" 2>/dev/null || true
fi

python "$SCRIPT_DIR/harness_metrics.py" \
  extract-opencode-metrics \
  "$EVENTS_PATH" \
  "$EXPORT_PATH" \
  > "$TASK_METRICS_PATH" 2>/dev/null || true
