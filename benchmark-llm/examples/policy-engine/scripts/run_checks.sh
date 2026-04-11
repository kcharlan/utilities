#!/usr/bin/env bash
set -euo pipefail

cd "$BENCH_WORKSPACE"

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt pytest

python "$BENCH_BENCHMARK_DIR/scripts/run_checks.py" \
  "$BENCH_RUN_DIR" \
  "$BENCH_WORKSPACE" \
  "$BENCH_HIDDEN_DIR"
