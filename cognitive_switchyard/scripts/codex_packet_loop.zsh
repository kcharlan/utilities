#!/usr/bin/env zsh

set -euo pipefail

source ~/.zshrc >/dev/null 2>&1 || true

SCRIPT_DIR="${0:A:h}"
SCRIPT_NAME="${0:t}"
DEFAULT_ROOT_DIR="${SCRIPT_DIR:h}"
ROOT_DIR="${ROOT_DIR:-$DEFAULT_ROOT_DIR}"
DESIGN_DOC="${DESIGN_DOC:-$ROOT_DIR/docs/cognitive_switchyard_design.md}"
DESIGN_PACKETIZATION_PLAYBOOK="${DESIGN_PACKETIZATION_PLAYBOOK:-$ROOT_DIR/docs/design_doc_packetization_playbook.md}"
IMPLEMENTATION_PLAYBOOK="${IMPLEMENTATION_PLAYBOOK:-$ROOT_DIR/docs/implementation_packet_playbook.md}"
PLANS_DIR="${PLANS_DIR:-$ROOT_DIR/plans}"
AUDITS_DIR="${AUDITS_DIR:-$ROOT_DIR/audits}"
STATUS_MD="${STATUS_MD:-$PLANS_DIR/packet_status.md}"
STATUS_JSON="${STATUS_JSON:-$PLANS_DIR/packet_status.json}"
AUTOMATION_LOG_DIR="${AUTOMATION_LOG_DIR:-$ROOT_DIR/automation_logs}"
JSON_PROGRESS_PARSER="${JSON_PROGRESS_PARSER:-$ROOT_DIR/scripts/codex_json_progress.py}"
STOP_FLAG_FILE="${STOP_FLAG_FILE:-$AUTOMATION_LOG_DIR/stop_after_current_stage.flag}"
STAGE_RETRY_STATE_JSON="${STAGE_RETRY_STATE_JSON:-$AUDITS_DIR/stage_retry_state.json}"

MODEL_NAME="${MODEL_NAME:-gpt-5.4}"
SERVICE_TIER="${SERVICE_TIER:-}"
AUTO_COMMIT_VALIDATED="${AUTO_COMMIT_VALIDATED:-false}"
BOOTSTRAP_EFFORT="${BOOTSTRAP_EFFORT:-high}"
PLANNER_EFFORT="${PLANNER_EFFORT:-high}"
IMPLEMENTER_EFFORT="${IMPLEMENTER_EFFORT:-medium}"
VALIDATOR_EFFORT="${VALIDATOR_EFFORT:-high}"
AUDIT_EFFORT="${AUDIT_EFFORT:-high}"

PACKET_HORIZON="${PACKET_HORIZON:-2}"
BOOTSTRAP_PACKET_HORIZON="${BOOTSTRAP_PACKET_HORIZON:-3}"
DRIFT_AUDIT_INTERVAL="${DRIFT_AUDIT_INTERVAL:-3}"
DRIFT_AUTO_FIX_MAX_EFFORT="${DRIFT_AUTO_FIX_MAX_EFFORT:-small}"
MAX_CYCLES="${MAX_CYCLES:-200}"
HEARTBEAT_INTERVAL="${HEARTBEAT_INTERVAL:-30}"
STALL_DIAGNOSTIC_AFTER="${STALL_DIAGNOSTIC_AFTER:-600}"
STALL_DIAGNOSTIC_INTERVAL="${STALL_DIAGNOSTIC_INTERVAL:-300}"
VALIDATOR_IDLE_TIMEOUT="${VALIDATOR_IDLE_TIMEOUT:-900}"
DRIFT_AUDIT_IDLE_TIMEOUT="${DRIFT_AUDIT_IDLE_TIMEOUT:-900}"
MAX_STAGE_TIMEOUT_RETRIES="${MAX_STAGE_TIMEOUT_RETRIES:-1}"

RUN_ID="$(date +%Y%m%d_%H%M%S)"
RUN_DIR="$AUTOMATION_LOG_DIR/$RUN_ID"
DRIFT_AUDIT_STATE_JSON="${DRIFT_AUDIT_STATE_JSON:-$AUDITS_DIR/drift_audit_state.json}"

mkdir -p "$PLANS_DIR" "$AUDITS_DIR" "$RUN_DIR"

log() {
  print -r -- "[$(date +%H:%M:%S)] $*"
}

die() {
  print -r -- "ERROR: $*" >&2
  exit 1
}

stop_requested() {
  [[ -f "$STOP_FLAG_FILE" ]]
}

clear_stop_flag() {
  rm -f "$STOP_FLAG_FILE"
}

request_stop() {
  mkdir -p "${STOP_FLAG_FILE:h}"
  : > "$STOP_FLAG_FILE"
}

honor_stop_request() {
  local context="$1"
  if stop_requested; then
    log "Stop requested; exiting after $context"
    return 0
  fi
  return 1
}

require_file() {
  local path="$1"
  [[ -f "$path" ]] || die "Missing required file: $path"
}

repo_rel_path() {
  local path="${1:A}"
  local root="${ROOT_DIR:A}"
  if [[ "$path" == "$root"/* ]]; then
    print -r -- "${path#$root/}"
  else
    print -r -- "$1"
  fi
}

stage_slug() {
  print -r -- "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/_/g; s/^_+//; s/_+$//'
}

heartbeat_summary() {
  local state_file="$1"
  python3 - "$state_file" <<'PY'
import json
import sys
import time

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    state = json.load(fh)

age = max(0, int(time.time() - state.get("timestamp", time.time())))
event_type = state.get("event_type", "unknown")
summary = state.get("summary", "").strip() or "no summary"
print(f"last event {age}s ago [{event_type}]: {summary}")
PY
}

heartbeat_age_seconds() {
  local state_file="$1"
  python3 - "$state_file" <<'PY'
import json
import sys
import time

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    state = json.load(fh)

print(max(0, int(time.time() - state.get("timestamp", time.time()))))
PY
}

write_stall_diagnostic() {
  local stage="$1"
  local codex_pid="$2"
  local state_file="$3"
  local event_log="$4"
  local output_file="$5"
  local diagnostic_file="$6"

  python3 - "$stage" "$codex_pid" "$state_file" "$event_log" "$output_file" "$diagnostic_file" <<'PY'
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

stage = sys.argv[1]
codex_pid = sys.argv[2]
state_file = Path(sys.argv[3])
event_log = Path(sys.argv[4])
output_file = Path(sys.argv[5])
diagnostic_file = Path(sys.argv[6])

state: dict[str, object] = {}
if state_file.exists():
    state = json.loads(state_file.read_text(encoding="utf-8"))

def stat_summary(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"exists": False}
    stat = path.stat()
    return {
        "exists": True,
        "size": stat.st_size,
        "mtime_epoch": int(stat.st_mtime),
        "mtime_local": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
    }

ps = subprocess.run(
    ["ps", "-o", "pid,ppid,etime,state,%cpu,%mem,command", "-p", codex_pid],
    check=False,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
)

tail = ""
if event_log.exists():
    with event_log.open("r", encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()[-5:]
    tail = "".join(lines).strip()

payload = {
    "captured_at_epoch": int(time.time()),
    "captured_at_local": time.strftime("%Y-%m-%d %H:%M:%S"),
    "stage": stage,
    "codex_pid": int(codex_pid),
    "state": state,
    "event_log": stat_summary(event_log),
    "output_file": stat_summary(output_file),
    "ps": ps.stdout.strip(),
    "recent_event_log_tail": tail,
}

diagnostic_file.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

write_stage_timeout_marker() {
  local stage="$1"
  local codex_pid="$2"
  local state_file="$3"
  local diagnostic_file="$4"
  local timeout_file="$5"
  local idle_timeout="$6"

  python3 - "$stage" "$codex_pid" "$state_file" "$diagnostic_file" "$timeout_file" "$idle_timeout" <<'PY'
from __future__ import annotations

import json
import time
import sys
from pathlib import Path

stage = sys.argv[1]
codex_pid = int(sys.argv[2])
state_file = Path(sys.argv[3])
diagnostic_file = Path(sys.argv[4])
timeout_file = Path(sys.argv[5])
idle_timeout = int(sys.argv[6])

state: dict[str, object] = {}
if state_file.exists():
    state = json.loads(state_file.read_text(encoding="utf-8"))

payload = {
    "captured_at_epoch": int(time.time()),
    "captured_at_local": time.strftime("%Y-%m-%d %H:%M:%S"),
    "stage": stage,
    "codex_pid": codex_pid,
    "idle_timeout_seconds": idle_timeout,
    "last_event_type": state.get("event_type", ""),
    "last_event_summary": state.get("summary", ""),
    "last_event_timestamp": state.get("timestamp"),
    "diagnostic_file": str(diagnostic_file) if diagnostic_file.exists() else "",
}

timeout_file.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

monitor_codex_heartbeat() {
  local stage="$1"
  local codex_pid="$2"
  local state_file="$3"
  local event_log="$4"
  local output_file="$5"
  local diagnostic_file="$6"
  local idle_timeout="$7"
  local timeout_file="$8"
  local last_diagnostic_age=-1

  while kill -0 "$codex_pid" 2>/dev/null; do
    sleep "$HEARTBEAT_INTERVAL"
    kill -0 "$codex_pid" 2>/dev/null || break

    local size=0
    [[ -f "$event_log" ]] && size="$(stat -f '%z' "$event_log" 2>/dev/null || echo 0)"

    if [[ -s "$state_file" ]]; then
      local age
      age="$(heartbeat_age_seconds "$state_file")"
      log "$stage still running; $(heartbeat_summary "$state_file"); event log ${size} bytes"

      if (( age >= STALL_DIAGNOSTIC_AFTER )) && (( last_diagnostic_age < 0 || age - last_diagnostic_age >= STALL_DIAGNOSTIC_INTERVAL )); then
        write_stall_diagnostic "$stage" "$codex_pid" "$state_file" "$event_log" "$output_file" "$diagnostic_file"
        last_diagnostic_age="$age"
        log "$stage stall diagnostic captured at $(repo_rel_path "$diagnostic_file")"
      fi

      if (( idle_timeout > 0 && age >= idle_timeout )); then
        write_stall_diagnostic "$stage" "$codex_pid" "$state_file" "$event_log" "$output_file" "$diagnostic_file"
        write_stage_timeout_marker "$stage" "$codex_pid" "$state_file" "$diagnostic_file" "$timeout_file" "$idle_timeout"
        log "$stage exceeded idle timeout of ${idle_timeout}s; terminating Codex process"
        kill -TERM "$codex_pid" 2>/dev/null || true
        sleep 5
        kill -0 "$codex_pid" 2>/dev/null && kill -KILL "$codex_pid" 2>/dev/null || true
        break
      fi
    else
      log "$stage still running; no events received yet; event log ${size} bytes"
    fi
  done
}

run_codex_exec() {
  local stage="$1"
  local effort="$2"
  local prompt_file="$3"
  local output_file="$4"
  local idle_timeout="${5:-0}"
  local slug event_log state_file diagnostic_file timeout_file codex_pid exit_code
  local -a codex_args

  command -v codex >/dev/null 2>&1 || die "'codex' is not available"
  require_file "$JSON_PROGRESS_PARSER"

  log "Running $stage with reasoning effort '$effort'"
  slug="$(stage_slug "$stage")"
  event_log="$RUN_DIR/${slug}.events.jsonl"
  state_file="$RUN_DIR/${slug}.state.json"
  diagnostic_file="$RUN_DIR/${slug}.stall_diagnostic.json"
  timeout_file="$RUN_DIR/${slug}.timeout.json"
  : > "$event_log"
  rm -f "$state_file"
  rm -f "$diagnostic_file"
  rm -f "$timeout_file"
  log "Streaming $stage events to $event_log"

  codex_args=(
    exec
    --dangerously-bypass-approvals-and-sandbox
    --skip-git-repo-check
    --color never
    --json
    -m "$MODEL_NAME"
    -c "model_reasoning_effort=\"$effort\""
    -C "$ROOT_DIR"
    -o "$output_file"
    -
  )

  if [[ -n "$SERVICE_TIER" ]]; then
    codex_args+=(-c "service_tier=\"$SERVICE_TIER\"")
  fi

  codex "${codex_args[@]}" < "$prompt_file" \
    > >(tee "$event_log" | python3 "$JSON_PROGRESS_PARSER" --stage "$stage" --state-file "$state_file") \
    2>&1 &
  codex_pid=$!

  monitor_codex_heartbeat "$stage" "$codex_pid" "$state_file" "$event_log" "$output_file" "$diagnostic_file" "$idle_timeout" "$timeout_file"
  wait "$codex_pid"
  exit_code=$?

  if [[ -f "$state_file" ]]; then
    log "$stage finished; $(heartbeat_summary "$state_file")"
  else
    log "$stage finished with no parsed events"
  fi

  if [[ -f "$timeout_file" ]]; then
    return 124
  fi

  return "$exit_code"
}

project_complete() {
  [[ -f "$STATUS_JSON" ]] || return 1
  [[ "$(python3 - "$STATUS_JSON" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    data = json.load(fh)

print("true" if data.get("project_complete", False) else "false")
PY
)" == "true" ]]
}

has_pending_packets() {
  [[ -f "$STATUS_JSON" ]] || return 1
  [[ "$(python3 - "$STATUS_JSON" "$ROOT_DIR" <<'PY'
import json
from pathlib import Path
import sys

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    data = json.load(fh)

pending = any(
    packet.get("status") in {"planned", "in_progress", "implemented"}
    and (Path(sys.argv[2]) / packet.get("doc", "")).is_file()
    for packet in data.get("packets", [])
)
print("true" if pending else "false")
PY
)" == "true" ]]
}

blocked_packet_summary() {
  [[ -f "$STATUS_JSON" ]] || return 1
  python3 - "$STATUS_JSON" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    data = json.load(fh)

blocked = [p for p in data.get("packets", []) if p.get("status") == "blocked"]
if blocked:
    first = sorted(blocked, key=lambda p: int(p["id"]))[0]
    print(f'{first["id"]}\t{first["doc"]}\t{first.get("notes", "")}')
PY
}

next_packet_info() {
  [[ -f "$STATUS_JSON" ]] || return 1
  python3 - "$STATUS_JSON" "$ROOT_DIR" <<'PY'
import json
from pathlib import Path
import sys

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    data = json.load(fh)

root_dir = Path(sys.argv[2])
pending = [
    p
    for p in data.get("packets", [])
    if p.get("status") in ("planned", "in_progress", "implemented")
    and (root_dir / p.get("doc", "")).is_file()
]
if not pending:
    sys.exit(1)

packet = sorted(pending, key=lambda p: int(p["id"]))[0]
print(f'{packet["id"]}\t{packet["status"]}\t{packet["doc"]}\t{packet["name"]}')
PY
}

packet_status_by_id() {
  local packet_id="$1"
  python3 - "$STATUS_JSON" "$packet_id" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    data = json.load(fh)

packet_id = sys.argv[2]
for packet in data.get("packets", []):
    if packet.get("id") == packet_id:
        print(packet.get("status", ""))
        break
PY
}

validated_packet_count() {
  [[ -f "$STATUS_JSON" ]] || {
    print -r -- "0"
    return 0
  }
  python3 - "$STATUS_JSON" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    data = json.load(fh)

count = sum(1 for packet in data.get("packets", []) if packet.get("status") == "validated")
print(count)
PY
}

highest_validated_packet_id() {
  [[ -f "$STATUS_JSON" ]] || return 1
  python3 - "$STATUS_JSON" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    data = json.load(fh)

validated = [packet for packet in data.get("packets", []) if packet.get("status") == "validated"]
if not validated:
    sys.exit(1)

packet = max(validated, key=lambda packet: int(packet["id"]))
print(packet["id"])
PY
}

should_run_periodic_drift_audit() {
  [[ -f "$STATUS_JSON" ]] || return 1
  local validated_count
  validated_count="$(validated_packet_count)"
  [[ "$validated_count" -gt 0 ]] || return 1

  [[ "$(python3 - "$DRIFT_AUDIT_STATE_JSON" "$validated_count" "$DRIFT_AUDIT_INTERVAL" <<'PY'
import json
from pathlib import Path
import sys

state_path = Path(sys.argv[1])
validated_count = int(sys.argv[2])
interval = int(sys.argv[3])

state = {}
if state_path.exists():
    with state_path.open("r", encoding="utf-8") as fh:
        state = json.load(fh)

last_count = state.get("last_audited_validated_count")
next_due = state.get("next_due_validated_count")

if last_count == validated_count:
    print("false")
elif next_due is not None:
    print("true" if validated_count >= int(next_due) else "false")
else:
    print("true" if validated_count >= interval and validated_count % interval == 0 else "false")
PY
)" == "true" ]]
}

final_drift_audit_needed() {
  project_complete || return 1
  has_pending_packets && return 1

  local highest_validated
  highest_validated="$(highest_validated_packet_id || true)"
  [[ -n "$highest_validated" ]] || return 1

  [[ "$(python3 - "$DRIFT_AUDIT_STATE_JSON" "$highest_validated" <<'PY'
import json
from pathlib import Path
import sys

state_path = Path(sys.argv[1])
highest_validated = sys.argv[2]

state = {}
if state_path.exists():
    with state_path.open("r", encoding="utf-8") as fh:
        state = json.load(fh)

print("true" if state.get("final_audited_packet_id") != highest_validated else "false")
PY
)" == "true" ]]
}

drift_audit_result_field() {
  local result_file="$1"
  local field_name="$2"
  python3 - "$result_file" "$field_name" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    data = json.load(fh)

value = data.get(sys.argv[2], "")
if isinstance(value, bool):
    print("true" if value else "false")
else:
    print(value)
PY
}

git_repo_available() {
  command -v git >/dev/null 2>&1 || return 1
  git -C "$ROOT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1
}

packet_commit_paths() {
  local packet_doc="$1"
  local validation_audit_doc="$2"
  python3 - "$ROOT_DIR" "$packet_doc" "$validation_audit_doc" <<'PY'
from __future__ import annotations

import fnmatch
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
packet_doc = Path(sys.argv[2])
validation_audit_doc = sys.argv[3]

text = packet_doc.read_text(encoding="utf-8")
lines = text.splitlines()

patterns: list[str] = []
in_allowed = False
for line in lines:
    if line.startswith("## "):
        if in_allowed:
            break
        in_allowed = line.strip() == "## Allowed Files"
        continue
    if not in_allowed:
        continue
    stripped = line.strip()
    if not stripped.startswith("- "):
        continue
    value = stripped[2:].strip().strip("`")
    if value:
        patterns.append(value)

always_include = ["plans/packet_status.md", "plans/packet_status.json"]
if validation_audit_doc:
    always_include.append(validation_audit_doc)

def git_lines(args: list[str]) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]

changed = set(git_lines(["diff", "--name-only", "--relative"]))
changed.update(git_lines(["diff", "--cached", "--name-only", "--relative"]))
changed.update(git_lines(["ls-files", "--others", "--exclude-standard"]))

def matches(path: str, pattern: str) -> bool:
    if pattern.endswith("/**"):
        prefix = pattern[:-3].rstrip("/")
        return path == prefix or path.startswith(prefix + "/")
    if pattern.endswith("/"):
        prefix = pattern.rstrip("/")
        return path == prefix or path.startswith(prefix + "/")
    if any(ch in pattern for ch in "*?["):
        return fnmatch.fnmatch(path, pattern)
    return path == pattern

selected = set()
for path in changed:
    if any(matches(path, pattern) for pattern in patterns):
        selected.add(path)

for path in always_include:
    if path in changed or (root / path).exists():
        selected.add(path)

for path in sorted(selected):
    print(path)
PY
}

auto_commit_validated_packet() {
  local packet_id="$1"
  local packet_doc="$2"
  local packet_name="$3"
  local validation_audit_doc commit_hash
  local -a commit_paths

  [[ "$AUTO_COMMIT_VALIDATED" == "true" ]] || return 0
  git_repo_available || {
    log "Auto-commit skipped; git repo unavailable"
    return 0
  }

  validation_audit_doc="audits/$(basename "$packet_doc" .md)_validation.md"
  commit_paths=("${(@f)$(packet_commit_paths "$packet_doc" "$validation_audit_doc")}")

  if (( ${#commit_paths[@]} == 0 )); then
    log "Auto-commit skipped; no packet-scoped changes detected for packet $packet_id"
    return 0
  fi

  git -C "$ROOT_DIR" add -- "${commit_paths[@]}"
  if git -C "$ROOT_DIR" diff --cached --quiet --exit-code; then
    log "Auto-commit skipped; nothing staged for packet $packet_id"
    return 0
  fi

  git -C "$ROOT_DIR" commit -m "Validate packet $packet_id: $packet_name" >/dev/null
  commit_hash="$(git -C "$ROOT_DIR" rev-parse --short HEAD)"
  log "Committed validated packet $packet_id as $commit_hash"
}

increment_stage_timeout_count() {
  local stage_key="$1"
  python3 - "$STAGE_RETRY_STATE_JSON" "$stage_key" <<'PY'
import json
from pathlib import Path
import sys

state_path = Path(sys.argv[1])
stage_key = sys.argv[2]

state = {}
if state_path.exists():
    state = json.loads(state_path.read_text(encoding="utf-8"))

entry = state.get(stage_key, {})
count = int(entry.get("timeout_count", 0)) + 1
entry["timeout_count"] = count
state[stage_key] = entry
state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(count)
PY
}

clear_stage_timeout_count() {
  local stage_key="$1"
  python3 - "$STAGE_RETRY_STATE_JSON" "$stage_key" <<'PY'
import json
from pathlib import Path
import sys

state_path = Path(sys.argv[1])
stage_key = sys.argv[2]

if not state_path.exists():
    raise SystemExit(0)

state = json.loads(state_path.read_text(encoding="utf-8"))
if stage_key in state:
    del state[stage_key]
    if state:
        state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        state_path.unlink()
PY
}

write_stage_timeout_report() {
  local stage_label="$1"
  local report_md="$2"
  local report_json="$3"
  local timeout_file="$4"
  local diagnostic_file="$5"
  local attempt_count="$6"
  local retry_limit="$7"

  python3 - "$stage_label" "$report_md" "$report_json" "$timeout_file" "$diagnostic_file" "$attempt_count" "$retry_limit" <<'PY'
from __future__ import annotations

import json
import time
import sys
from pathlib import Path

stage_label = sys.argv[1]
report_md = Path(sys.argv[2])
report_json = Path(sys.argv[3])
timeout_file = Path(sys.argv[4])
diagnostic_file = Path(sys.argv[5])
attempt_count = int(sys.argv[6])
retry_limit = int(sys.argv[7])

timeout_data = {}
if timeout_file.exists():
    timeout_data = json.loads(timeout_file.read_text(encoding="utf-8"))

payload = {
    "captured_at_epoch": int(time.time()),
    "captured_at_local": time.strftime("%Y-%m-%d %H:%M:%S"),
    "stage": stage_label,
    "timeout": timeout_data,
    "attempt_count": attempt_count,
    "retry_limit": retry_limit,
    "diagnostic_file": str(diagnostic_file) if diagnostic_file.exists() else "",
}
report_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

lines = [
    f"# Stage Timeout: {stage_label}",
    "",
    f"- Captured: {payload['captured_at_local']}",
    f"- Attempt count: {attempt_count}",
    f"- Retry limit: {retry_limit}",
    f"- Idle timeout seconds: {timeout_data.get('idle_timeout_seconds', '')}",
    f"- Last event type: {timeout_data.get('last_event_type', '')}",
    f"- Last event summary: {timeout_data.get('last_event_summary', '')}",
]
if payload["diagnostic_file"]:
    lines.append(f"- Stall diagnostic: `{payload['diagnostic_file']}`")
lines.extend(
    [
        "",
        "The stage exceeded its idle timeout and was terminated by the packet loop harness.",
        "A retry may occur if the retry budget has not been exhausted.",
        "",
        f"Machine-readable companion: `{report_json}`",
    ]
)
report_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
}

handle_timeout_retry_or_halt() {
  local stage_key="$1"
  local stage_label="$2"
  local report_md="$3"
  local report_json="$4"
  local timeout_file="$5"
  local diagnostic_file="$6"
  local timeout_count

  timeout_count="$(increment_stage_timeout_count "$stage_key")"
  write_stage_timeout_report "$stage_label" "$report_md" "$report_json" "$timeout_file" "$diagnostic_file" "$timeout_count" "$MAX_STAGE_TIMEOUT_RETRIES"

  if (( timeout_count <= MAX_STAGE_TIMEOUT_RETRIES )); then
    log "$stage_label timed out; retrying (${timeout_count}/${MAX_STAGE_TIMEOUT_RETRIES})"
    return 0
  fi

  die "$stage_label timed out again after ${timeout_count} attempts. See $(repo_rel_path "$report_md")"
}

update_drift_audit_state() {
  local result_file="$1"
  local report_file="$2"
  local is_final="$3"
  local validated_count highest_validated

  validated_count="$(validated_packet_count)"
  highest_validated="$(highest_validated_packet_id || true)"

  python3 - "$DRIFT_AUDIT_STATE_JSON" "$result_file" "$report_file" "$validated_count" "$highest_validated" "$DRIFT_AUDIT_INTERVAL" "$is_final" <<'PY'
import json
from pathlib import Path
import sys

state_path = Path(sys.argv[1])
result_path = Path(sys.argv[2])
report_path = Path(sys.argv[3])
validated_count = int(sys.argv[4])
highest_validated = sys.argv[5]
interval = int(sys.argv[6])
is_final = sys.argv[7] == "true"

with result_path.open("r", encoding="utf-8") as fh:
    result = json.load(fh)

state = {}
if state_path.exists():
    with state_path.open("r", encoding="utf-8") as fh:
        state = json.load(fh)

status = result.get("status", "")
if status == "warn":
    next_due = validated_count + 1
else:
    next_due = validated_count + interval

state.update(
    {
        "last_audited_validated_count": validated_count,
        "last_audited_packet_id": highest_validated or None,
        "last_result": status,
        "next_due_validated_count": next_due,
        "last_audit_result_file": str(result_path),
        "last_audit_report_file": str(report_path),
    }
)
if is_final:
    state["final_audited_packet_id"] = highest_validated or None

state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

bootstrap_needed() {
  [[ ! -f "$IMPLEMENTATION_PLAYBOOK" || ! -f "$STATUS_JSON" ]]
}

write_bootstrap_prompt() {
  local prompt_file="$1"
  cat > "$prompt_file" <<EOF
Read \`$(repo_rel_path "$DESIGN_PACKETIZATION_PLAYBOOK")\` and follow it exactly.

Task:
Analyze the design document at \`$(repo_rel_path "$DESIGN_DOC")\` and generate the packetized implementation system for this project.

Instructions:
- Read \`$(repo_rel_path "$DESIGN_PACKETIZATION_PLAYBOOK")\` first.
- Read the design document at \`$(repo_rel_path "$DESIGN_DOC")\`.
- Read the current codebase in \`$ROOT_DIR\`.
- Create or update \`$(repo_rel_path "$IMPLEMENTATION_PLAYBOOK")\`.
- Create or update \`plans/packet_status.md\`.
- Create or update \`plans/packet_status.json\`.
- If the codebase already contains implemented work, reflect that in the trackers instead of pretending the project is empty.
- Create exactly the first $BOOTSTRAP_PACKET_HORIZON remaining packet docs under \`plans/\`.
- Keep the initial packets biased toward contracts, fixtures, parsing, and pure logic.
- Make the output directly usable by future planner, implementer, and validator agents.

Required outputs:
- \`$(repo_rel_path "$IMPLEMENTATION_PLAYBOOK")\`
- \`plans/packet_status.md\`
- \`plans/packet_status.json\`
- first $BOOTSTRAP_PACKET_HORIZON remaining packet docs under \`plans/\`
EOF
}

write_planner_prompt() {
  local prompt_file="$1"
  cat > "$prompt_file" <<EOF
Read \`$(repo_rel_path "$IMPLEMENTATION_PLAYBOOK")\` and follow it exactly.

Task:
Plan the next $PACKET_HORIZON packets for this project using the current codebase and \`$(repo_rel_path "$DESIGN_DOC")\`.

Instructions:
- Read \`$(repo_rel_path "$IMPLEMENTATION_PLAYBOOK")\` first.
- Read \`plans/packet_status.md\` and \`plans/packet_status.json\` if they exist.
- Read only the relevant sections of \`$(repo_rel_path "$DESIGN_DOC")\`.
- Read the current codebase to determine the current implementation state.
- Identify the highest validated packet.
- Produce exactly the next $PACKET_HORIZON packet docs, no more.
- Keep each packet narrowly scoped to one behavior family.
- Use the required packet template from the implementation playbook.
- Include tests-to-write-first, explicit non-goals, allowed files, and acceptance criteria.
- Update both trackers.
- If no packets remain after the validated frontier, set \`project_complete\` to \`true\`.

Required outputs:
- updated \`plans/packet_status.md\`
- updated \`plans/packet_status.json\`
- next $PACKET_HORIZON packet docs under \`plans/\`
EOF
}

write_implementer_prompt() {
  local prompt_file="$1"
  local packet_doc="$2"
  cat > "$prompt_file" <<EOF
Read \`$(repo_rel_path "$IMPLEMENTATION_PLAYBOOK")\` and follow it exactly.

Task:
Implement exactly one packet: \`$packet_doc\`.

Instructions:
- Read only this packet doc, the files it references, and the specific design doc sections named in the packet.
- Do not broaden scope beyond the packet.
- Write tests first.
- Implement the packet.
- Run the packet tests and any directly affected regressions.
- If the packet is under-specified, make the minimum safe assumption and document it.
- Do not start the next packet.
- Update \`plans/packet_status.md\` and \`plans/packet_status.json\` to \`implemented\` only if tests pass.

Deliver:
- code changes for this packet only
- tests for this packet
- brief note of anything deferred because it belongs to a later packet
EOF
}

write_validator_prompt() {
  local prompt_file="$1"
  local packet_doc="$2"
  cat > "$prompt_file" <<EOF
Read \`$(repo_rel_path "$IMPLEMENTATION_PLAYBOOK")\` and follow it exactly.

Task:
Validate and repair exactly one implemented packet: \`$packet_doc\`.

Instructions:
- Read the packet doc first.
- Review the changed code and tests against packet scope.
- Focus on correctness, edge cases, weak tests, regressions, and scope creep.
- Run the packet tests and any obviously impacted regressions.
- Once the decisive packet-scope evidence is available, finish the validation immediately.
- If tests pass and no concrete packet-scope defect remains, write the validation audit and update the trackers to \`validated\` without doing more broad exploration.
- If you find issues inside packet scope, fix them now.
- Strengthen weak tests if needed.
- Do not continue large design-doc or reference-system exploration after passing tests unless a specific unresolved packet-scope issue requires it.
- Do not add features from later packets.
- Write \`audits/$(basename "$packet_doc" .md)_validation.md\`.
- Update \`plans/packet_status.md\` and \`plans/packet_status.json\` to \`validated\` if acceptable, otherwise \`blocked\`.
EOF
}

write_drift_audit_prompt() {
  local prompt_file="$1"
  local audit_md="$2"
  local audit_json="$3"
  local audit_label="$4"
  local highest_validated="$5"
  local validated_count="$6"
  cat > "$prompt_file" <<EOF
Read \`$(repo_rel_path "$IMPLEMENTATION_PLAYBOOK")\` and follow it exactly.

Task:
Run a cumulative drift audit for the packetized implementation flow: \`$audit_label\`.

Instructions:
- Read \`$(repo_rel_path "$IMPLEMENTATION_PLAYBOOK")\` first.
- Read \`plans/packet_status.md\` and \`plans/packet_status.json\`.
- Read the validated packet docs up to and including packet \`$highest_validated\`.
- Read the relevant sections of \`$(repo_rel_path "$DESIGN_DOC")\`.
- Inspect the current codebase and any existing files under \`audits/\` that affect this drift review.
- Compare the cumulative implementation and packet ladder against the intended architecture, packet boundaries, canonical contracts, and design-doc constraints.
- Focus on architectural drift, scope creep across packets, invalid tracker state, missing cross-packet corrections, and places where the current path is diverging from the intended delivery system.
- If you find a low-severity issue that is small effort to fix safely right now, fix it now and rerun the targeted validation needed to support that fix.
- Do not perform medium- or high-effort repairs in this audit. Record them instead.
- Do not broaden scope into future packets.
- Do not change \`plans/packet_status.md\` or \`plans/packet_status.json\` during this audit.
- Write a human-readable report to \`$(repo_rel_path "$audit_md")\`.
- Write a machine-readable result to \`$(repo_rel_path "$audit_json")\`.

The JSON result must have exactly this shape:
\`\`\`json
{
  "status": "pass|fix_now|warn|halt",
  "severity": "low|medium|high",
  "effort": "small|medium|high",
  "summary": "short summary",
  "fixes_applied": false,
  "validation_rerun": "none|targeted|broader",
  "notes": ""
}
\`\`\`

Decision rules:
- Use \`pass\` when there is no meaningful drift.
- Use \`fix_now\` only when severity is \`low\` and effort is \`small\`, and the fix stays tightly scoped.
- Use \`warn\` for medium drift or anything that should be corrected soon but does not justify halting the run.
- Use \`halt\` for high-severity drift, contract violations, architecture breakage, or issues that will compound dangerously if the run continues.

Context:
- Audit label: \`$audit_label\`
- Highest validated packet: \`$highest_validated\`
- Validated packet count: \`$validated_count\`
- Maximum allowed auto-fix effort in this audit: \`$DRIFT_AUTO_FIX_MAX_EFFORT\`
EOF
}

run_bootstrap() {
  require_file "$DESIGN_DOC"
  require_file "$DESIGN_PACKETIZATION_PLAYBOOK"

  local prompt_file="$RUN_DIR/bootstrap.prompt.txt"
  local output_file="$RUN_DIR/bootstrap.last_message.txt"

  write_bootstrap_prompt "$prompt_file"
  run_codex_exec "bootstrap" "$BOOTSTRAP_EFFORT" "$prompt_file" "$output_file"
  honor_stop_request "bootstrap" && return 0

  require_file "$IMPLEMENTATION_PLAYBOOK"
  require_file "$STATUS_JSON"
}

run_planner() {
  require_file "$IMPLEMENTATION_PLAYBOOK"

  local prompt_file="$RUN_DIR/planner.prompt.txt"
  local output_file="$RUN_DIR/planner.last_message.txt"

  write_planner_prompt "$prompt_file"
  run_codex_exec "planner" "$PLANNER_EFFORT" "$prompt_file" "$output_file"
  honor_stop_request "planner" && return 0

  require_file "$STATUS_JSON"
}

run_implementer() {
  local packet_id="$1"
  local packet_doc="$2"
  local prompt_file="$RUN_DIR/packet_${packet_id}_implement.prompt.txt"
  local output_file="$RUN_DIR/packet_${packet_id}_implement.last_message.txt"

  require_file "$packet_doc"
  write_implementer_prompt "$prompt_file" "$packet_doc"
  run_codex_exec "implementer packet $packet_id" "$IMPLEMENTER_EFFORT" "$prompt_file" "$output_file"
  honor_stop_request "implementer packet $packet_id" && return 0
}

run_validator() {
  local packet_id="$1"
  local packet_doc="$2"
  local prompt_file="$RUN_DIR/packet_${packet_id}_validate.prompt.txt"
  local output_file="$RUN_DIR/packet_${packet_id}_validate.last_message.txt"
  local stage_key="validator:$packet_id"
  local timeout_report_md="$AUDITS_DIR/packet_${packet_id}_validator_timeout.md"
  local timeout_report_json="$AUDITS_DIR/packet_${packet_id}_validator_timeout.json"
  local timeout_file="$RUN_DIR/validator_packet_${packet_id}.timeout.json"
  local diagnostic_file="$RUN_DIR/validator_packet_${packet_id}.stall_diagnostic.json"

  require_file "$packet_doc"
  write_validator_prompt "$prompt_file" "$packet_doc"
  while true; do
    run_codex_exec "validator packet $packet_id" "$VALIDATOR_EFFORT" "$prompt_file" "$output_file" "$VALIDATOR_IDLE_TIMEOUT"
    local exit_code=$?
    if [[ "$exit_code" -eq 0 ]]; then
      clear_stage_timeout_count "$stage_key"
      break
    fi
    if [[ "$exit_code" -eq 124 ]]; then
      handle_timeout_retry_or_halt "$stage_key" "validator packet $packet_id" "$timeout_report_md" "$timeout_report_json" "$timeout_file" "$diagnostic_file"
      continue
    fi
    return "$exit_code"
  done
  honor_stop_request "validator packet $packet_id" && return 0
}

run_drift_audit() {
  local audit_label="$1"
  local is_final="$2"
  local highest_validated validated_count audit_slug audit_md audit_json prompt_file output_file result_status result_severity result_effort stage_key timeout_report_md timeout_report_json timeout_file diagnostic_file

  highest_validated="$(highest_validated_packet_id || true)"
  [[ -n "$highest_validated" ]] || die "Cannot run drift audit without a validated packet"
  validated_count="$(validated_packet_count)"
  audit_slug="$(stage_slug "$audit_label")"
  audit_md="$AUDITS_DIR/${audit_slug}.md"
  audit_json="$AUDITS_DIR/${audit_slug}.json"
  prompt_file="$RUN_DIR/${audit_slug}.prompt.txt"
  output_file="$RUN_DIR/${audit_slug}.last_message.txt"
  stage_key="drift_audit:${highest_validated}:${is_final}"
  timeout_report_md="$AUDITS_DIR/${audit_slug}_timeout.md"
  timeout_report_json="$AUDITS_DIR/${audit_slug}_timeout.json"
  timeout_file="$RUN_DIR/${audit_slug}.timeout.json"
  diagnostic_file="$RUN_DIR/${audit_slug}.stall_diagnostic.json"

  write_drift_audit_prompt "$prompt_file" "$audit_md" "$audit_json" "$audit_label" "$highest_validated" "$validated_count"
  while true; do
    run_codex_exec "$audit_label" "$AUDIT_EFFORT" "$prompt_file" "$output_file" "$DRIFT_AUDIT_IDLE_TIMEOUT"
    local exit_code=$?
    if [[ "$exit_code" -eq 0 ]]; then
      clear_stage_timeout_count "$stage_key"
      break
    fi
    if [[ "$exit_code" -eq 124 ]]; then
      handle_timeout_retry_or_halt "$stage_key" "$audit_label" "$timeout_report_md" "$timeout_report_json" "$timeout_file" "$diagnostic_file"
      continue
    fi
    return "$exit_code"
  done
  honor_stop_request "$audit_label" && return 0

  require_file "$audit_md"
  require_file "$audit_json"

  result_status="$(drift_audit_result_field "$audit_json" "status")"
  result_severity="$(drift_audit_result_field "$audit_json" "severity")"
  result_effort="$(drift_audit_result_field "$audit_json" "effort")"

  case "$result_status" in
    pass|fix_now|warn|halt)
      ;;
    *)
      die "Drift audit returned invalid status '$result_status' in $audit_json"
      ;;
  esac

  if [[ "$result_status" == "fix_now" ]]; then
    [[ "$result_severity" == "low" && "$result_effort" == "small" ]] || die "Drift audit status 'fix_now' requires severity=low and effort=small; got severity='$result_severity' effort='$result_effort'"
  fi

  update_drift_audit_state "$audit_json" "$audit_md" "$is_final"

  case "$result_status" in
    pass)
      log "Drift audit passed: $(drift_audit_result_field "$audit_json" "summary")"
      ;;
    fix_now)
      log "Drift audit fixed a low-severity issue: $(drift_audit_result_field "$audit_json" "summary")"
      ;;
    warn)
      log "Drift audit warning: $(drift_audit_result_field "$audit_json" "summary")"
      ;;
    halt)
      die "Drift audit halted the run: $(drift_audit_result_field "$audit_json" "summary"). See $(repo_rel_path "$audit_md")"
      ;;
  esac
}

maybe_run_periodic_drift_audit() {
  should_run_periodic_drift_audit || return 0
  run_drift_audit "drift audit after packet $(highest_validated_packet_id)" "false"
}

maybe_run_final_drift_audit() {
  final_drift_audit_needed || return 0
  run_drift_audit "final drift audit after packet $(highest_validated_packet_id)" "true"
}

fail_if_blocked() {
  local blocked
  blocked="$(blocked_packet_summary || true)"
  if [[ -n "$blocked" ]]; then
    local packet_id packet_doc notes
    IFS=$'\t' read -r packet_id packet_doc notes <<< "$blocked"
    die "Packet $packet_id is blocked. See $packet_doc${notes:+ -- $notes}"
  fi
}

run_one_cycle() {
  local packet packet_id packet_status packet_doc packet_name updated_status

  fail_if_blocked

  if project_complete && ! has_pending_packets; then
    log "Project is complete according to $STATUS_JSON"
    return 1
  fi

  if ! has_pending_packets; then
    log "No actionable packet docs found. Invoking planner."
    run_planner
    fail_if_blocked

    if project_complete && ! has_pending_packets; then
      log "Planner marked project complete."
      return 1
    fi

    has_pending_packets || die "Planner produced no actionable packet docs and did not mark project complete"
  fi

  packet="$(next_packet_info || true)"
  [[ -n "$packet" ]] || die "Unable to determine the next packet from $STATUS_JSON"

  IFS=$'\t' read -r packet_id packet_status packet_doc packet_name <<< "$packet"
  log "Next packet: $packet_id [$packet_status] $packet_name"

  if [[ "$packet_status" == "implemented" ]]; then
    run_validator "$packet_id" "$packet_doc"
    honor_stop_request "validator packet $packet_id" && return 1
    updated_status="$(packet_status_by_id "$packet_id")"
    [[ "$updated_status" == "validated" ]] || die "Validator did not mark packet $packet_id as validated; current status is '$updated_status'"
    log "Packet $packet_id validated"
    auto_commit_validated_packet "$packet_id" "$packet_doc" "$packet_name"
    maybe_run_periodic_drift_audit
    return 0
  fi

  run_implementer "$packet_id" "$packet_doc"
  honor_stop_request "implementer packet $packet_id" && return 1
  updated_status="$(packet_status_by_id "$packet_id")"

  case "$updated_status" in
    implemented)
      log "Packet $packet_id implemented; invoking validator"
      run_validator "$packet_id" "$packet_doc"
      honor_stop_request "validator packet $packet_id" && return 1
      updated_status="$(packet_status_by_id "$packet_id")"
      [[ "$updated_status" == "validated" ]] || die "Validator did not mark packet $packet_id as validated; current status is '$updated_status'"
      log "Packet $packet_id validated"
      auto_commit_validated_packet "$packet_id" "$packet_doc" "$packet_name"
      maybe_run_periodic_drift_audit
      ;;
    validated)
      log "Packet $packet_id was fully validated during implementation"
      auto_commit_validated_packet "$packet_id" "$packet_doc" "$packet_name"
      maybe_run_periodic_drift_audit
      ;;
    blocked)
      die "Packet $packet_id became blocked during implementation"
      ;;
    *)
      die "Implementer did not advance packet $packet_id to implemented; current status is '$updated_status'"
      ;;
  esac
}

cmd_bootstrap() {
  bootstrap_needed || {
    log "Bootstrap files already exist."
    return 0
  }
  run_bootstrap
  log "Bootstrap complete"
}

cmd_plan() {
  bootstrap_needed && run_bootstrap
  honor_stop_request "bootstrap" && return 0
  run_planner
  log "Planning complete"
}

cmd_status() {
  if [[ ! -f "$STATUS_JSON" ]]; then
    log "No status tracker at $STATUS_JSON"
    return 0
  fi

  python3 - "$STATUS_JSON" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    data = json.load(fh)

print(f'project_complete={data.get("project_complete", False)}')
print(f'highest_validated_packet={data.get("highest_validated_packet")}')
for packet in data.get("packets", []):
    print(f'{packet["id"]}\t{packet["status"]}\t{packet["doc"]}')
PY

  if stop_requested; then
    log "stop_requested=true"
  else
    log "stop_requested=false"
  fi
}

cmd_stop() {
  request_stop
  log "Stop requested. The current stage will finish, then the loop will exit."
}

cmd_clear_stop() {
  clear_stop_flag
  log "Cleared stop request."
}

cmd_run() {
  clear_stop_flag

  if bootstrap_needed; then
    log "Bootstrap artifacts missing. Running bootstrap."
    run_bootstrap
    honor_stop_request "bootstrap" && return 0
  fi

  local cycle=1
  while (( cycle <= MAX_CYCLES )); do
    log "Cycle $cycle"
    if ! run_one_cycle; then
      break
    fi
    ((cycle++))
  done

  if (( cycle > MAX_CYCLES )); then
    die "Reached MAX_CYCLES=$MAX_CYCLES without completing the project"
  fi

  maybe_run_final_drift_audit
  log "Automation run finished. Logs: $RUN_DIR"
}

usage() {
  cat <<EOF
Usage: $SCRIPT_NAME [bootstrap|plan|run|status|stop|clear-stop|help]

Commands:
  bootstrap   Create the implementation packet system from the design doc if missing
  plan        Generate the next packet batch
  run         Bootstrap if needed, then loop plan -> implement -> validate -> periodic drift audit
  status      Print the machine-readable packet tracker in a compact form
  stop        Request a clean stop after the current stage completes
  clear-stop  Clear a previously requested stop
  help        Show this help text

Environment overrides:
  ROOT_DIR, DESIGN_DOC, IMPLEMENTATION_PLAYBOOK, PACKET_HORIZON
  MODEL_NAME, SERVICE_TIER, AUTO_COMMIT_VALIDATED, BOOTSTRAP_EFFORT, PLANNER_EFFORT, IMPLEMENTER_EFFORT, VALIDATOR_EFFORT, AUDIT_EFFORT
  DRIFT_AUDIT_INTERVAL, DRIFT_AUTO_FIX_MAX_EFFORT, MAX_CYCLES, HEARTBEAT_INTERVAL
  STALL_DIAGNOSTIC_AFTER, STALL_DIAGNOSTIC_INTERVAL
  VALIDATOR_IDLE_TIMEOUT, DRIFT_AUDIT_IDLE_TIMEOUT, MAX_STAGE_TIMEOUT_RETRIES

Examples:
  ./scripts/codex_packet_loop.zsh bootstrap
  ./scripts/codex_packet_loop.zsh run
  SERVICE_TIER=fast ./scripts/codex_packet_loop.zsh run
  SERVICE_TIER=fast AUTO_COMMIT_VALIDATED=true ./scripts/codex_packet_loop.zsh run
  DRIFT_AUDIT_INTERVAL=2 ./scripts/codex_packet_loop.zsh run
  STALL_DIAGNOSTIC_AFTER=300 ./scripts/codex_packet_loop.zsh run
  VALIDATOR_IDLE_TIMEOUT=600 DRIFT_AUDIT_IDLE_TIMEOUT=600 ./scripts/codex_packet_loop.zsh run
  ./scripts/codex_packet_loop.zsh stop
  ./scripts/codex_packet_loop.zsh clear-stop
EOF
}

main() {
  local command="${1:-run}"

  case "$command" in
    -h|--help|help)
      usage
      ;;
    bootstrap)
      cmd_bootstrap
      ;;
    plan)
      cmd_plan
      ;;
    run)
      cmd_run
      ;;
    status)
      cmd_status
      ;;
    stop)
      cmd_stop
      ;;
    clear-stop)
      cmd_clear_stop
      ;;
    *)
      usage
      exit 1
      ;;
  esac
}

main "$@"
