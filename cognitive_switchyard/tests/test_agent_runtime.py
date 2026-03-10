from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from cognitive_switchyard.agent_runtime import ClaudeCliRuntime, ClaudeCliRuntimeError


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
        "-p",
        "Planner prompt only.",
    ]
