from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def send_notification(
    *,
    title: str,
    message: str,
    report_path: Path | None,
    open_target: str,
) -> None:
    if sys.platform != "darwin":
        return
    if report_path is not None:
        message = _with_report_path(message=message, report_path=report_path, open_target=open_target)
    escaped_title = title.replace('"', '\\"')
    escaped_message = message.replace('"', '\\"')
    script = f'display notification "{escaped_message}" with title "{escaped_title}"'
    subprocess.run(["osascript", "-e", script], check=False, capture_output=True)


def _with_report_path(*, message: str, report_path: Path, open_target: str) -> str:
    target = report_path if open_target == "file" else report_path.parent
    suffix = f" Path: {target}"
    combined = f"{message}{suffix}"
    if len(combined) <= 240:
        return combined
    return message
