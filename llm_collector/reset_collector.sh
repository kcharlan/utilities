#!/bin/bash
# reset_collector.sh — clears LLM counters at midnight

# allowing some delay in case coming out of a suspend.
sleep 5

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
  echo "Error: Docker is not running." >&2
  exit 1
fi

# Check if the llm_collector_container is running
if ! docker ps --filter "name=llm" --filter "status=running" | grep -q "llm_collector_container"; then
  echo "Error: The llm_collector_container is not running." >&2
  exit 1
fi

API_KEY="<your key here>"
MAX_RETRIES=3
RETRY_COUNT=0
BACKOFF=3

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
  if curl -s -X POST -H "X-API-KEY: $API_KEY" http://127.0.0.1:9000/reset >> /Users/kevinharlan/llm_collector/collector.log 2>&1; then
    exit 0
  fi

  RETRY_COUNT=$((RETRY_COUNT + 1))
  if [ $RETRY_COUNT -lt $MAX_RETRIES ]; then
    sleep $((BACKOFF * RETRY_COUNT))
  fi
done

echo "Error: Failed to reset collector after $MAX_RETRIES attempts." >&2
exit 1
