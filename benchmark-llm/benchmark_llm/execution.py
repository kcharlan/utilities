from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .metrics import normalize_metrics
from .util import elapsed_milliseconds, iso_timestamp, utc_now


def _load_metrics_payload(metrics_path: Path | None) -> tuple[dict[str, Any] | None, str | None]:
    if metrics_path is None or not metrics_path.exists():
        return None, None
    try:
        payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, str(exc)
    if not isinstance(payload, dict):
        return None, "Metrics payload must be a JSON object."
    return normalize_metrics(payload), None


def run_command(
    command: str,
    cwd: Path,
    env: dict[str, str],
    phase: str,
    metrics_path: Path | None = None,
) -> dict[str, Any]:
    started = utc_now()
    if metrics_path is not None:
        metrics_path.parent.mkdir(parents=True, exist_ok=True)
        if metrics_path.exists():
            metrics_path.unlink()
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        shell=True,
        capture_output=True,
        text=True,
    )
    ended = utc_now()
    metrics, metrics_error = _load_metrics_payload(metrics_path)
    record = {
        "phase": phase,
        "command": command,
        "cwd": str(cwd),
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "started_at": iso_timestamp(started),
        "ended_at": iso_timestamp(ended),
        "elapsed_ms": elapsed_milliseconds(started, ended),
    }
    if metrics is not None:
        record["metrics"] = metrics
    if metrics_path is not None:
        record["metrics_path"] = str(metrics_path)
    if metrics_error is not None:
        record["metrics_error"] = metrics_error
    return record
