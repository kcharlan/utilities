from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def send_notification(
    *,
    title: str,
    message: str,
    report_path: Path | None,
    open_target: str,
    runtime_home: Path | None = None,
) -> None:
    del runtime_home
    if sys.platform != "darwin":
        return
    target_path = _notification_target_path(report_path=report_path, open_target=open_target)
    terminal_notifier = shutil.which("terminal-notifier")
    if terminal_notifier and target_path is not None:
        _send_terminal_notifier(
            executable=terminal_notifier,
            title=title,
            message=message,
            target_path=target_path,
        )
        return
    if report_path is not None:
        message = _with_report_path(message=message, report_path=report_path, open_target=open_target)
    _send_plain_notification(title=title, message=message)


def _send_plain_notification(*, title: str, message: str) -> None:
    escaped_title = title.replace('"', '\\"')
    escaped_message = message.replace('"', '\\"')
    script = f'display notification "{escaped_message}" with title "{escaped_title}"'
    subprocess.run(["osascript", "-e", script], check=False, capture_output=True)


def _send_terminal_notifier(*, executable: str, title: str, message: str, target_path: Path) -> None:
    subprocess.run(
        [
            executable,
            "-title",
            title,
            "-message",
            message,
            "-open",
            target_path.resolve().as_uri(),
        ],
        check=False,
        capture_output=True,
    )


def _notification_target_path(*, report_path: Path | None, open_target: str) -> Path | None:
    if report_path is None:
        return None
    if open_target == "file":
        return report_path
    if open_target == "folder":
        return report_path.parent
    return None


def _with_report_path(*, message: str, report_path: Path, open_target: str) -> str:
    target = report_path if open_target == "file" else report_path.parent
    suffix = f" Path: {target}"
    combined = f"{message}{suffix}"
    if len(combined) <= 240:
        return combined
    return message
