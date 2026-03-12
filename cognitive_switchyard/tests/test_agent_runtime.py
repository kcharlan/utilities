from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import json

from cognitive_switchyard.agent_runtime import (
    ClaudeCliRuntime,
    ClaudeCliRuntimeError,
    _extract_detail_from_stream_json,
    _extract_result_text_from_stream_json,
)


def test_claude_cli_runner_builds_planner_invocation_from_model_prompt_and_session_inputs(
    tmp_path: Path,
) -> None:
    (tmp_path / "system.md").write_text("Shared system rules.\n", encoding="utf-8")
    prompt_path = tmp_path / "planner.md"
    prompt_path.write_text("Planner system prompt.\n", encoding="utf-8")
    intake_path = tmp_path / "001_feature.md"
    intake_path.write_text("# Feature\nImplement packet 13.\n", encoding="utf-8")
    session_root = tmp_path / "session-root"
    session_root.mkdir()

    captured: dict[str, object] = {}

    def fake_runner(*, command: list[str], cwd: Path, input_text: str) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured["cwd"] = cwd
        captured["input_text"] = input_text
        return subprocess.CompletedProcess(command, 0, stdout="planned output\n", stderr="")

    runtime = ClaudeCliRuntime(command="claude", subprocess_runner=fake_runner)

    result = runtime.run_planner(
        model="claude-opus-4-1",
        prompt_path=prompt_path,
        intake_path=intake_path,
        intake_text=intake_path.read_text(encoding="utf-8"),
        session_root=session_root,
    )

    assert result == "planned output\n"
    assert captured["cwd"] == session_root
    assert captured["command"] == [
        "claude",
        "--dangerously-skip-permissions",
        "--model",
        "claude-opus-4-1",
        "--output-format",
        "stream-json",
        "--verbose",
        "-p",
        "Shared system rules.\n\nPlanner system prompt.",
    ]
    assert captured["input_text"] == (
        f"Session root: {session_root}\n"
        f"Intake file: {intake_path}\n"
        "--- BEGIN INTAKE ---\n"
        "# Feature\n"
        "Implement packet 13.\n"
        "--- END INTAKE ---\n"
    )


@pytest.mark.parametrize(
    ("completed", "message_fragment"),
    [
        (
            subprocess.CompletedProcess(["claude"], 2, stdout="", stderr="boom"),
            "exit code 2",
        ),
        (
            subprocess.CompletedProcess(["claude"], 0, stdout=" \n", stderr=""),
            "did not produce output",
        ),
    ],
)
def test_claude_cli_runner_raises_typed_error_on_non_zero_exit_or_missing_output(
    tmp_path: Path,
    completed: subprocess.CompletedProcess[str],
    message_fragment: str,
) -> None:
    prompt_path = tmp_path / "planner.md"
    prompt_path.write_text("Planner prompt.\n", encoding="utf-8")

    runtime = ClaudeCliRuntime(
        command="claude",
        subprocess_runner=lambda **_: completed,
    )

    with pytest.raises(ClaudeCliRuntimeError) as excinfo:
        runtime.run_planner(
            model="claude-opus-4-1",
            prompt_path=prompt_path,
            intake_path=tmp_path / "001_feature.md",
            intake_text="test\n",
            session_root=tmp_path,
        )

    error = excinfo.value
    assert error.phase == "planning"
    assert message_fragment in str(error)


def test_claude_cli_runner_uses_phase_prompt_when_shared_system_prompt_is_absent(
    tmp_path: Path,
) -> None:
    prompt_path = tmp_path / "planner.md"
    prompt_path.write_text("Planner prompt only.\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_runner(*, command: list[str], cwd: Path, input_text: str) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")

    runtime = ClaudeCliRuntime(command="claude", subprocess_runner=fake_runner)

    runtime.run_planner(
        model="claude-opus-4-1",
        prompt_path=prompt_path,
        intake_path=tmp_path / "001_feature.md",
        intake_text="test\n",
        session_root=tmp_path,
    )

    assert captured["command"] == [
        "claude",
        "--dangerously-skip-permissions",
        "--model",
        "claude-opus-4-1",
        "--output-format",
        "stream-json",
        "--verbose",
        "-p",
        "Planner prompt only.",
    ]


# --- Regression tests for stream-json NDJSON parsing helpers ---


def test_extract_detail_system_line_returns_init_message() -> None:
    line = json.dumps({"type": "system", "subtype": "init", "session_id": "abc"})
    assert _extract_detail_from_stream_json(line) == "CLI initialized (session started)"


def test_extract_detail_assistant_with_tool_use_returns_tool_names() -> None:
    line = json.dumps({
        "type": "assistant",
        "message": {
            "content": [
                {"type": "tool_use", "id": "1", "name": "Read", "input": {}},
                {"type": "tool_use", "id": "2", "name": "Edit", "input": {}},
            ]
        },
    })
    result = _extract_detail_from_stream_json(line)
    assert result == "Using: Read, Edit"


def test_extract_detail_assistant_text_only_returns_first_line_truncated() -> None:
    long_text = "A" * 100 + "\nSecond line"
    line = json.dumps({
        "type": "assistant",
        "message": {
            "content": [{"type": "text", "text": long_text}],
        },
    })
    result = _extract_detail_from_stream_json(line)
    assert result is not None
    assert len(result) <= 80
    assert result == "A" * 80


def test_extract_detail_result_line_returns_completed_prefix() -> None:
    line = json.dumps({"type": "result", "result": "Done with the task.\nMore text."})
    result = _extract_detail_from_stream_json(line)
    assert result is not None
    assert result.startswith("Completed: ")
    assert "Done with the task." in result


def test_extract_detail_other_type_returns_none() -> None:
    line = json.dumps({"type": "rate_limit_event", "data": {}})
    assert _extract_detail_from_stream_json(line) is None


def test_extract_detail_malformed_json_returns_none() -> None:
    assert _extract_detail_from_stream_json("not json at all") is None
    assert _extract_detail_from_stream_json("{broken") is None


def test_extract_detail_non_json_line_returns_none() -> None:
    assert _extract_detail_from_stream_json("##PROGRESS## 001 | Phase: implementing | 3/5") is None


def test_extract_result_text_finds_result_line() -> None:
    ndjson = "\n".join([
        json.dumps({"type": "system", "subtype": "init"}),
        json.dumps({"type": "assistant", "message": {"content": []}}),
        json.dumps({"type": "result", "result": "The plan is complete.\n\nSee attached."}),
    ]) + "\n"
    result = _extract_result_text_from_stream_json(ndjson)
    assert result == "The plan is complete.\n\nSee attached."


def test_extract_result_text_falls_back_to_raw_if_no_result_line() -> None:
    raw = "plain text output\nnot NDJSON\n"
    result = _extract_result_text_from_stream_json(raw)
    assert result == raw


def test_extract_result_text_handles_empty_result_field() -> None:
    ndjson = "\n".join([
        json.dumps({"type": "system"}),
        json.dumps({"type": "result", "result": ""}),
    ]) + "\n"
    # Falls back to raw since result field is empty string
    result = _extract_result_text_from_stream_json(ndjson)
    assert result == ""


def test_claude_cli_command_includes_stream_json_flags(tmp_path: Path) -> None:
    """Regression: stream-json flags must always be in the command."""
    prompt_path = tmp_path / "planner.md"
    prompt_path.write_text("prompt\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_runner(*, command: list[str], cwd: Path, input_text: str) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout="output\n", stderr="")

    runtime = ClaudeCliRuntime(command="claude", subprocess_runner=fake_runner)
    runtime.run_planner(
        model="sonnet",
        prompt_path=prompt_path,
        intake_path=tmp_path / "001.md",
        intake_text="test\n",
        session_root=tmp_path,
    )

    cmd = captured["command"]
    assert "--output-format" in cmd
    assert "stream-json" in cmd
    assert "--verbose" in cmd
