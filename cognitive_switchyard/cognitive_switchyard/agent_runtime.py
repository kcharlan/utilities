from __future__ import annotations

import os
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .models import FixerAttemptResult, FixerContext, PackManifest


SubprocessRunner = Callable[..., subprocess.CompletedProcess[str]]
OutputLineCallback = Callable[[str, str], None]  # (phase, line)


@dataclass(frozen=True)
class ClaudeCliRuntimeError(RuntimeError):
    phase: str
    message: str
    command: tuple[str, ...]
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""

    def __str__(self) -> str:
        return self.message


class ClaudeCliRuntime:
    def __init__(
        self,
        *,
        command: str = "claude",
        subprocess_runner: SubprocessRunner | None = None,
        output_line_callback: OutputLineCallback | None = None,
    ) -> None:
        self.command = command
        self._subprocess_runner = subprocess_runner or _default_subprocess_runner
        self._output_line_callback = output_line_callback

    def planner_agent(
        self,
        *,
        model: str,
        prompt_path: Path,
        intake_path: Path,
        intake_text: str,
        session_root: Path,
        **_: object,
    ) -> str:
        return self.run_planner(
            model=model,
            prompt_path=prompt_path,
            intake_path=intake_path,
            intake_text=intake_text,
            session_root=session_root,
        )

    def resolver_agent(
        self,
        *,
        model: str,
        prompt_path: Path,
        session_root: Path,
        staged_plans,
        plan_paths,
        **_: object,
    ) -> str:
        sections = [f"Session root: {session_root}\n", "Staged plans:\n"]
        for index, (plan_path, staged_plan) in enumerate(zip(plan_paths, staged_plans, strict=False), start=1):
            sections.extend(
                [
                    f"\n[{index}] {plan_path}\n",
                    "--- BEGIN PLAN ---\n",
                    staged_plan.body,
                    "\n--- END PLAN ---\n",
                ]
            )
        return self._run_phase(
            phase="resolution",
            model=model,
            prompt_path=prompt_path,
            session_root=session_root,
            input_text="".join(sections),
        )

    def fixer_executor(self, context: FixerContext, *, model: str, prompt_path: Path, session_root: Path):
        try:
            output = self._run_phase(
                phase="auto_fix",
                model=model,
                prompt_path=prompt_path,
                session_root=session_root,
                input_text=_format_fixer_context(context),
            )
        except ClaudeCliRuntimeError as exc:
            return FixerAttemptResult(success=False, summary=str(exc))
        return FixerAttemptResult(success=True, summary=output.strip())

    def run_planner(
        self,
        *,
        model: str,
        prompt_path: Path,
        intake_path: Path,
        intake_text: str,
        session_root: Path,
    ) -> str:
        return self._run_phase(
            phase="planning",
            model=model,
            prompt_path=prompt_path,
            session_root=session_root,
            input_text=(
                f"Session root: {session_root}\n"
                f"Intake file: {intake_path}\n"
                "--- BEGIN INTAKE ---\n"
                f"{intake_text}"
                "--- END INTAKE ---\n"
            ),
        )

    def _run_phase(
        self,
        *,
        phase: str,
        model: str,
        prompt_path: Path,
        session_root: Path,
        input_text: str,
    ) -> str:
        prompt_text = _load_prompt_bundle(prompt_path)
        command = [
            self.command,
            "--dangerously-skip-permissions",
            "--model",
            model,
            "-p",
            prompt_text,
        ]
        if self._output_line_callback is not None:
            self._output_line_callback(phase, f"[{phase}] Launching Claude CLI ({model})...")
            completed = _streaming_subprocess_runner(
                command=command,
                cwd=session_root,
                input_text=input_text,
                line_callback=lambda line: self._output_line_callback(phase, line),
            )
            self._output_line_callback(
                phase,
                f"[{phase}] Claude CLI finished (exit {completed.returncode})",
            )
        else:
            completed = self._subprocess_runner(
                command=command,
                cwd=session_root,
                input_text=input_text,
            )
        if completed.returncode != 0:
            stderr = completed.stderr or ""
            stdout = completed.stdout or ""
            details = stderr.strip() or stdout.strip() or "Claude CLI failed"
            raise ClaudeCliRuntimeError(
                phase=phase,
                message=f"Claude CLI {phase} failed with exit code {completed.returncode}: {details}",
                command=tuple(command),
                exit_code=completed.returncode,
                stdout=stdout,
                stderr=stderr,
            )
        output = completed.stdout or ""
        if not output.strip():
            raise ClaudeCliRuntimeError(
                phase=phase,
                message=f"Claude CLI {phase} did not produce output.",
                command=tuple(command),
                exit_code=completed.returncode,
                stdout=output,
                stderr=completed.stderr or "",
            )
        return output


def build_default_agent_runtime(
    pack_manifest: PackManifest,
    output_line_callback: OutputLineCallback | None = None,
) -> ClaudeCliRuntime:
    del pack_manifest
    return ClaudeCliRuntime(output_line_callback=output_line_callback)


def _default_subprocess_runner(
    *,
    command: list[str],
    cwd: Path,
    input_text: str,
) -> subprocess.CompletedProcess[str]:
    # Strip CLAUDECODE env var so child Claude CLI sessions don't refuse to
    # launch when the orchestrator itself is running inside Claude Code.
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    return subprocess.run(
        command,
        cwd=cwd,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def _streaming_subprocess_runner(
    *,
    command: list[str],
    cwd: Path,
    input_text: str,
    line_callback: Callable[[str], None],
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess while streaming stdout lines through a callback.

    Returns a CompletedProcess with the full captured stdout/stderr, compatible
    with the non-streaming runner.
    """
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    proc = subprocess.Popen(
        command,
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=env,
    )
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    def _read_stderr():
        assert proc.stderr is not None
        for raw_line in iter(proc.stderr.readline, ""):
            stderr_lines.append(raw_line)
        proc.stderr.close()

    stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
    stderr_thread.start()

    # Write input and close stdin
    assert proc.stdin is not None
    try:
        proc.stdin.write(input_text)
        proc.stdin.close()
    except BrokenPipeError:
        pass

    # Read stdout line-by-line, streaming to callback
    assert proc.stdout is not None
    for raw_line in iter(proc.stdout.readline, ""):
        stdout_lines.append(raw_line)
        line_callback(raw_line.rstrip("\r\n"))
    proc.stdout.close()

    stderr_thread.join(timeout=5.0)
    proc.wait()
    return subprocess.CompletedProcess(
        args=command,
        returncode=proc.returncode,
        stdout="".join(stdout_lines),
        stderr="".join(stderr_lines),
    )


def _format_fixer_context(context: FixerContext) -> str:
    sections = [
        f"Context type: {context.context_type}\n",
        f"Session id: {context.session_id}\n",
        f"Task id: {context.task_id or 'none'}\n",
        f"Attempt: {context.attempt}\n",
    ]
    if context.plan_text:
        sections.extend(["--- BEGIN PLAN ---\n", context.plan_text, "\n--- END PLAN ---\n"])
    if context.status_text:
        sections.extend(["--- BEGIN STATUS ---\n", context.status_text, "\n--- END STATUS ---\n"])
    if context.worker_log_tail:
        sections.extend(["--- BEGIN WORKER LOG ---\n", context.worker_log_tail, "\n--- END WORKER LOG ---\n"])
    if context.verification_output:
        sections.extend(
            ["--- BEGIN VERIFICATION ---\n", context.verification_output, "\n--- END VERIFICATION ---\n"]
        )
    if context.previous_attempt_summary:
        sections.append(f"Previous attempt summary: {context.previous_attempt_summary}\n")
    return "".join(sections)


def _load_prompt_bundle(prompt_path: Path) -> str:
    prompt_text = prompt_path.read_text(encoding="utf-8").strip()
    system_prompt_path = prompt_path.with_name("system.md")
    if not system_prompt_path.is_file():
        return prompt_text
    system_text = system_prompt_path.read_text(encoding="utf-8").strip()
    if not system_text:
        return prompt_text
    return f"{system_text}\n\n{prompt_text}"
