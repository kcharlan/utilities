from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


def _write_executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


@pytest.mark.parametrize("pack_name", ["claude-code", "codex"])
def test_builtin_verify_uses_source_repo_venv_for_worktree_sessions_and_runs_from_repo_root(
    tmp_path: Path,
    repo_root: Path,
    pack_name: str,
) -> None:
    pack_root = repo_root / "cognitive_switchyard" / "builtin_packs" / pack_name
    worktree_root = tmp_path / "worktree-repo"
    source_root = tmp_path / "source-repo"
    worktree_root.mkdir()
    source_root.mkdir()
    (worktree_root / "tests").mkdir()

    trace_path = tmp_path / f"{pack_name}-source-trace.txt"
    _write_executable(
        source_root / ".venv" / "bin" / "pytest",
        """#!/bin/sh
set -eu
{
  pwd
  printf '%s\\n' "$*"
} > "$TRACE_PATH"
exit 0
""",
    )

    result = subprocess.run(
        [str(pack_root / "scripts" / "verify"), str(tmp_path / "session-root")],
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ["PATH"],
            "TRACE_PATH": str(trace_path),
            "COGNITIVE_SWITCHYARD_PACK_ROOT": str(pack_root),
            "COGNITIVE_SWITCHYARD_REPO_ROOT": str(worktree_root),
            "COGNITIVE_SWITCHYARD_SOURCE_REPO": str(source_root),
        },
    )

    assert result.returncode == 0, result.stderr or result.stdout
    trace_lines = trace_path.read_text(encoding="utf-8").splitlines()
    assert trace_lines == [
        str(worktree_root),
        "tests --tb=short -q",
    ]


@pytest.mark.parametrize("pack_name", ["claude-code", "codex"])
def test_builtin_verify_never_falls_back_to_switchyard_bootstrap_venv(
    tmp_path: Path,
    repo_root: Path,
    pack_name: str,
) -> None:
    pack_root = repo_root / "cognitive_switchyard" / "builtin_packs" / pack_name
    target_root = tmp_path / "repo-root"
    target_root.mkdir()
    (target_root / "tests").mkdir()

    home_dir = tmp_path / "home"
    bootstrap_trace = tmp_path / f"{pack_name}-bootstrap-trace.txt"
    path_trace = tmp_path / f"{pack_name}-path-trace.txt"
    _write_executable(
        home_dir / ".cognitive_switchyard_venv" / "bin" / "pytest",
        """#!/bin/sh
set -eu
echo bootstrap > "$BOOTSTRAP_TRACE"
exit 99
""",
    )

    fake_bin = tmp_path / "bin"
    _write_executable(
        fake_bin / "pytest",
        """#!/bin/sh
set -eu
{
  pwd
  printf '%s\\n' "$*"
} > "$PATH_TRACE"
exit 0
""",
    )

    result = subprocess.run(
        [str(pack_root / "scripts" / "verify"), str(tmp_path / "session-root")],
        capture_output=True,
        text=True,
        env={
            "HOME": str(home_dir),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "BOOTSTRAP_TRACE": str(bootstrap_trace),
            "PATH_TRACE": str(path_trace),
            "COGNITIVE_SWITCHYARD_PACK_ROOT": str(pack_root),
            "COGNITIVE_SWITCHYARD_REPO_ROOT": str(target_root),
        },
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert not bootstrap_trace.exists(), "Verify script must not use the switchyard bootstrap venv"
    trace_lines = path_trace.read_text(encoding="utf-8").splitlines()
    assert trace_lines == [
        str(target_root),
        "tests --tb=short -q",
    ]
