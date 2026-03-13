from pathlib import Path

from model_sentinel.notifications import _with_report_path


def test_with_report_path_appends_file_path_for_file_target() -> None:
    message = _with_report_path(
        message="Changes detected.",
        report_path=Path("/tmp/model_sentinel/report.md"),
        open_target="file",
    )
    assert message.endswith("Path: /tmp/model_sentinel/report.md")


def test_with_report_path_appends_parent_path_for_folder_target() -> None:
    message = _with_report_path(
        message="Changes detected.",
        report_path=Path("/tmp/model_sentinel/report.md"),
        open_target="folder",
    )
    assert message.endswith("Path: /tmp/model_sentinel")


def test_with_report_path_falls_back_to_original_message_when_too_long() -> None:
    original = "x" * 241
    message = _with_report_path(
        message=original,
        report_path=Path("/tmp/model_sentinel/report.md"),
        open_target="file",
    )
    assert message == original
