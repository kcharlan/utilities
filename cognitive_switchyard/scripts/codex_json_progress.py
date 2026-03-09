#!/usr/bin/env python3

import argparse
import json
import sys
import time
from pathlib import Path


def now() -> str:
    return time.strftime("%H:%M:%S")


def truncate(text: str, limit: int = 180) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def write_state(state_path: Path, event_type: str, summary: str) -> None:
    payload = {
        "timestamp": time.time(),
        "event_type": event_type,
        "summary": summary,
    }
    tmp_path = state_path.with_suffix(state_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload), encoding="utf-8")
    tmp_path.replace(state_path)


def event_summary(event: dict) -> tuple[str, str, bool]:
    event_type = event.get("type", "unknown")

    if event_type == "thread.started":
        return event_type, "session started", True

    if event_type == "turn.started":
        return event_type, "turn started", True

    if event_type == "turn.completed":
        usage = event.get("usage", {})
        summary = (
            f"turn completed; input_tokens={usage.get('input_tokens', 0)} "
            f"output_tokens={usage.get('output_tokens', 0)}"
        )
        return event_type, summary, True

    if event_type == "item.completed":
        item = event.get("item", {})
        item_type = item.get("type", "unknown")
        if item_type == "agent_message":
            text = truncate(item.get("text", "agent message"))
            return event_type, text, True
        return event_type, f"item completed: {item_type}", False

    if event_type == "error":
        return event_type, truncate(json.dumps(event)), True

    return event_type, event_type, False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True)
    parser.add_argument("--state-file", required=True)
    args = parser.parse_args()

    state_path = Path(args.state_file)

    for raw_line in sys.stdin:
        line = raw_line.rstrip("\n")
        if not line.strip():
            continue

        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            summary = truncate(line)
            write_state(state_path, "raw", summary)
            print(f"[{now()}] {args.stage}: {summary}", flush=True)
            continue

        event_type, summary, should_print = event_summary(event)
        write_state(state_path, event_type, summary)
        if should_print:
            print(f"[{now()}] {args.stage}: {summary}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
