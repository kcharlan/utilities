from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
import time
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
    timeout_sec: int | None = None,
    inactivity_timeout_sec: int | None = None,
    stdout_path: Path | None = None,
    stderr_path: Path | None = None,
) -> dict[str, Any]:
    started = utc_now()
    if metrics_path is not None:
        metrics_path.parent.mkdir(parents=True, exist_ok=True)
        if metrics_path.exists():
            metrics_path.unlink()

    temp_paths: list[Path] = []
    if stdout_path is None:
        stdout_fd, stdout_name = tempfile.mkstemp(prefix="benchmark-llm-stdout-", suffix=".log")
        os.close(stdout_fd)
        stdout_path = Path(stdout_name)
        temp_paths.append(stdout_path)
    else:
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
    if stderr_path is None:
        stderr_fd, stderr_name = tempfile.mkstemp(prefix="benchmark-llm-stderr-", suffix=".log")
        os.close(stderr_fd)
        stderr_path = Path(stderr_name)
        temp_paths.append(stderr_path)
    else:
        stderr_path.parent.mkdir(parents=True, exist_ok=True)

    stdout_path.write_text("", encoding="utf-8")
    stderr_path.write_text("", encoding="utf-8")

    timed_out = False
    inactivity_timed_out = False

    with stdout_path.open("w", encoding="utf-8") as stdout_handle, stderr_path.open(
        "w", encoding="utf-8"
    ) as stderr_handle:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            shell=True,
            text=True,
            stdout=stdout_handle,
            stderr=stderr_handle,
            start_new_session=True,
        )

        deadline = time.monotonic() + timeout_sec if timeout_sec is not None else None
        last_activity = time.monotonic()
        last_sizes = (0, 0)

        while True:
            exit_code = process.poll()
            stdout_size = stdout_path.stat().st_size if stdout_path.exists() else 0
            stderr_size = stderr_path.stat().st_size if stderr_path.exists() else 0
            if (stdout_size, stderr_size) != last_sizes:
                last_sizes = (stdout_size, stderr_size)
                last_activity = time.monotonic()
            now = time.monotonic()
            if exit_code is not None:
                break
            if deadline is not None and now >= deadline:
                timed_out = True
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                break
            if inactivity_timeout_sec is not None and now - last_activity >= inactivity_timeout_sec:
                inactivity_timed_out = True
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                break
            time.sleep(0.25)

        completed = subprocess.CompletedProcess(
            command,
            process.returncode if process.returncode is not None else -signal.SIGTERM,
            stdout_path.read_text(encoding="utf-8"),
            stderr_path.read_text(encoding="utf-8"),
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
    if timeout_sec is not None:
        record["timeout_sec"] = timeout_sec
    if inactivity_timeout_sec is not None:
        record["inactivity_timeout_sec"] = inactivity_timeout_sec
    if timed_out:
        record["timed_out"] = True
    if inactivity_timed_out:
        record["inactivity_timed_out"] = True
    record["stdout_path"] = str(stdout_path)
    record["stderr_path"] = str(stderr_path)
    if metrics is not None:
        record["metrics"] = metrics
    if metrics_path is not None:
        record["metrics_path"] = str(metrics_path)
    if metrics_error is not None:
        record["metrics_error"] = metrics_error
    for path in temp_paths:
        try:
            path.unlink()
        except OSError:
            pass
    return record
