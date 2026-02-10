#!/bin/bash
# reset_collector.sh — clears LLM counters at midnight

# --- Configuration ---
# Optional override: set DOCKER_PATH explicitly if Docker is not on PATH.
DOCKER_PATH="${DOCKER_PATH:-$(command -v docker 2>/dev/null)}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_DIR="$SCRIPT_DIR"
LOG_FILE="$BASE_DIR/reset_launchd.log"
ERR_FILE="$BASE_DIR/reset_launchd.err"
API_KEY_FILE="$BASE_DIR/MY_API_KEY.txt"
MAX_LOG_LINES=100

# --- Command Paths ---
CURL_CMD="/usr/bin/curl"
GREP_CMD="/usr/bin/grep"
MV_CMD="/bin/mv"
WC_CMD="/usr/bin/wc"
XARGS_CMD="/usr/bin/xargs"
SLEEP_CMD="/bin/sleep"
CAT_CMD="/bin/cat"
DATE_CMD="/bin/date"

# --- Functions ---
log_error() {
  echo "$($DATE_CMD): ERROR: $1" >> "$ERR_FILE"
}

log_info() {
  echo "$($DATE_CMD): INFO: $1" >> "$LOG_FILE"
}

rotate_log() {
  local file="$1"
  local max_lines="$2"
  if [ -f "$file" ]; then
    local lines=$($WC_CMD -l < "$file" | $XARGS_CMD)
    if [ "$lines" -ge "$max_lines" ]; then
      $MV_CMD "$file" "$file.1"
    fi
  fi
}

# --- Main Script ---

# Rotate logs
rotate_log "$LOG_FILE" "$MAX_LOG_LINES"
rotate_log "$ERR_FILE" "$MAX_LOG_LINES"

log_info "Starting reset_collector.sh script."

# Delay for system to stabilize (e.g., after waking from sleep)
$SLEEP_CMD 5

# Check for Docker executable
if [ ! -x "$DOCKER_PATH" ]; then
  log_error "Docker executable not found or not executable at $DOCKER_PATH."
  exit 1
fi

# Check if Docker is running
if ! $DOCKER_PATH info > /dev/null 2>&1; then
  log_error "Docker is not running."
  exit 1
fi
log_info "Docker is running."

# Check if the llm_collector_container is running
if ! $DOCKER_PATH ps --format "{{.Names}}" | $GREP_CMD -Eq '^(llm-collector|llm_collector_container)$'; then
  log_error "The LLM collector container is not running."
  exit 1
fi
log_info "LLM collector container is running."

# Check for API key file
if [ ! -f "$API_KEY_FILE" ]; then
  log_error "API key file not found at $API_KEY_FILE."
  exit 1
fi

API_KEY=$($CAT_CMD "$API_KEY_FILE")
MAX_RETRIES=3
RETRY_COUNT=0
BACKOFF=3

log_info "Checking for active counters before reset."
COUNTERS_RESPONSE=$($CURL_CMD -s -H "X-API-KEY: $API_KEY" http://127.0.0.1:9000/counters)
if echo "$COUNTERS_RESPONSE" | $GREP_CMD -q '^{"counters":{}}$'; then
  log_info "No active counters found. No reset needed."
  exit 0
fi

log_info "Attempting to reset collector."
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
  if $CURL_CMD -s -X POST -H "X-API-KEY: $API_KEY" http://127.0.0.1:9000/reset >> "$LOG_FILE" 2>&1; then
    log_info "Collector reset successfully."
    exit 0
  fi

  RETRY_COUNT=$((RETRY_COUNT + 1))
  log_info "Collector reset failed. Retrying in $((BACKOFF * RETRY_COUNT)) seconds..."
  if [ $RETRY_COUNT -lt $MAX_RETRIES ]; then
    $SLEEP_CMD $((BACKOFF * RETRY_COUNT))
  fi
done

log_error "Failed to reset collector after $MAX_RETRIES attempts."
exit 1
