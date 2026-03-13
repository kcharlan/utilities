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
    escaped_title = title.replace('"', '\\"')
    escaped_message = message.replace('"', '\\"')
    script = f'display notification "{escaped_message}" with title "{escaped_title}"'
    subprocess.run(["osascript", "-e", script], check=False, capture_output=True)
    if report_path is None:
        return
    if open_target == "file" and report_path.exists():
        subprocess.run(["open", "-R", str(report_path)], check=False, capture_output=True)
        return
    target_dir = report_path.parent if report_path.exists() else report_path.parent
    subprocess.run(["open", str(target_dir)], check=False, capture_output=True)

