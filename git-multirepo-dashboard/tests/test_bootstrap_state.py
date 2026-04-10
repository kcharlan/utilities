import os
import subprocess
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import git_dashboard  # noqa: E402


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "git_dashboard.py"


def test_help_does_not_create_runtime_state(tmp_path):
    runtime_home = tmp_path / "runtime_home"
    env = os.environ.copy()
    env["GIT_DASHBOARD_HOME"] = str(runtime_home)
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--help"],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0
    assert "usage:" in result.stdout
    assert not runtime_home.exists()


def test_bootstrap_creates_state_and_reexecs(monkeypatch, tmp_path):
    monkeypatch.setenv("GIT_DASHBOARD_HOME", str(tmp_path / "runtime_home"))
    paths = git_dashboard.build_runtime_paths()
    installs = []

    def fake_create(self, path):
        python_path = paths.venv_python
        python_path.parent.mkdir(parents=True, exist_ok=True)
        python_path.write_text("", encoding="utf-8")

    def fake_install(runtime_paths):
        installs.append(runtime_paths)

    class Reexec(RuntimeError):
        pass

    def fake_execv(executable, argv):
        raise Reexec((executable, tuple(argv)))

    monkeypatch.setattr(git_dashboard.venv.EnvBuilder, "create", fake_create)
    monkeypatch.setattr(git_dashboard, "install_runtime_dependencies", fake_install)
    monkeypatch.setattr(git_dashboard.os, "execv", fake_execv)

    with pytest.raises(Reexec):
        git_dashboard.ensure_private_venv(paths)

    assert installs == [paths]
    assert paths.bootstrap_state.exists()
    assert paths.venv_python.exists()


def test_bootstrap_rebuilds_when_existing_python_fails_health_check(monkeypatch, tmp_path):
    monkeypatch.setenv("GIT_DASHBOARD_HOME", str(tmp_path / "runtime_home"))
    paths = git_dashboard.build_runtime_paths()
    paths.home.mkdir(parents=True, exist_ok=True)
    paths.venv_python.parent.mkdir(parents=True, exist_ok=True)
    paths.venv_python.write_text("", encoding="utf-8")
    paths.bootstrap_state.write_text(
        git_dashboard.json.dumps(git_dashboard.desired_bootstrap_state()),
        encoding="utf-8",
    )
    installs = []

    def fake_create(self, path):
        python_path = paths.venv_python
        python_path.parent.mkdir(parents=True, exist_ok=True)
        python_path.write_text("", encoding="utf-8")

    def fake_install(runtime_paths):
        installs.append(runtime_paths)

    class Reexec(RuntimeError):
        pass

    def fake_execv(executable, argv):
        raise Reexec((executable, tuple(argv)))

    monkeypatch.setattr(git_dashboard.sys, "prefix", str(tmp_path / "outside"))
    monkeypatch.setattr(git_dashboard.subprocess, "run", lambda *args, **kwargs: type("Result", (), {"returncode": 134})())
    monkeypatch.setattr(git_dashboard.venv.EnvBuilder, "create", fake_create)
    monkeypatch.setattr(git_dashboard, "install_runtime_dependencies", fake_install)
    monkeypatch.setattr(git_dashboard.os, "execv", fake_execv)

    with pytest.raises(Reexec):
        git_dashboard.ensure_private_venv(paths)

    assert installs == [paths]
