#!/bin/bash
# reset_collector.sh — clears LLM counters at midnight

BASE_DIR="/Users/kevinharlan/llm_collector"

LOG_FILE="$BASE_DIR/reset_launchd.log"
ERR_FILE="$BASE_DIR/reset_launchd.err"
MAX_LINES=100

# Rotate log file if it exceeds MAX_LINES
if [ -f "$LOG_FILE" ]; then
  LINES=$(wc -l < "$LOG_FILE" | xargs)
  if [ "$LINES" -ge "$MAX_LINES" ]; then
    mv "$LOG_FILE" "$LOG_FILE.1"
  fi
fi

# Rotate err file if it exceeds MAX_LINES
if [ -f "$ERR_FILE" ]; then
  LINES=$(wc -l < "$ERR_FILE" | xargs)
  if [ "$LINES" -ge "$MAX_LINES" ]; then
    mv "$ERR_FILE" "$ERR_FILE.1"
  fi
fi

# allowing some delay in case coming out of a suspend.
sleep 5

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
  echo "$(date): Error: Docker is not running." >&2
  exit 1
fi

# Check if the llm_collector_container is running
if ! docker ps --filter "name=llm" --filter "status=running" | grep -q "llm_collector_container"; then
  echo "$(date): Error: The llm_collector_container is not running." >&2
  exit 1
fi

API_KEY=$(cat "$BASE_DIR/MY_API_KEY.txt")
MAX_RETRIES=3
RETRY_COUNT=0
BACKOFF=3

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
  if curl -s -X POST -H "X-API-KEY: $API_KEY" http://127.0.0.1:9000/reset >> "$BASE_DIR/collector.log" 2>&1; then
    exit 0
  fi

  RETRY_COUNT=$((RETRY_COUNT + 1))
  if [ $RETRY_COUNT -lt $MAX_RETRIES ]; then
    sleep $((BACKOFF * RETRY_COUNT))
  fi
done

echo "$(date): Error: Failed to reset collector after $MAX_RETRIES attempts." >&2
exit 1