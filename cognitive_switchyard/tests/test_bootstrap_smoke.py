from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

from cognitive_switchyard import BOOTSTRAP_VENV, PACKAGE_NAME, RUNTIME_HOME


LEGACY_RUNTIME_MARKERS = ("~/.switchyard", "~/.switchyard_venv")


def run_command(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=repo_root,
        text=True,
        capture_output=True,
    )


def test_import_cognitive_switchyard() -> None:
    module = importlib.import_module("cognitive_switchyard")

    assert module.__name__ == "cognitive_switchyard"
    assert PACKAGE_NAME == "cognitive_switchyard"
    assert RUNTIME_HOME == "~/.cognitive_switchyard"
    assert BOOTSTRAP_VENV == "~/.cognitive_switchyard_venv"


def test_python_module_help_succeeds(repo_root: Path) -> None:
    result = run_command(repo_root, sys.executable, "-m", "cognitive_switchyard", "--help")

    assert result.returncode == 0
    assert "cognitive_switchyard" in result.stdout
    assert "runtime home" in result.stdout
    assert "~/.cognitive_switchyard" in result.stdout
    assert "~/.cognitive_switchyard_venv" in result.stdout
    for legacy_marker in LEGACY_RUNTIME_MARKERS:
        assert legacy_marker not in result.stdout
    assert result.stderr == ""


def test_switchyard_help_succeeds(repo_root: Path) -> None:
    launcher = repo_root / "switchyard"
    result = run_command(repo_root, str(launcher), "--help")

    assert result.returncode == 0
    assert "cognitive_switchyard" in result.stdout
    assert "~/.cognitive_switchyard" in result.stdout
    assert "~/.cognitive_switchyard_venv" in result.stdout
    for legacy_marker in LEGACY_RUNTIME_MARKERS:
        assert legacy_marker not in result.stdout
    assert result.stderr == ""


def test_paths_subcommand_reports_canonical_contracts(repo_root: Path) -> None:
    launcher = repo_root / "switchyard"
    result = run_command(repo_root, str(launcher), "paths")

    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        "package: cognitive_switchyard",
        "runtime home: ~/.cognitive_switchyard",
        "bootstrap venv: ~/.cognitive_switchyard_venv",
    ]
    assert result.stderr == ""
