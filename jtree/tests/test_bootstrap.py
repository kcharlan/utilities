import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "jtree"


def load_module(monkeypatch, runtime_home: Path):
    monkeypatch.setenv("JTREE_HOME", str(runtime_home))
    module_name = f"jtree_bootstrap_{uuid.uuid4().hex}"
    loader = importlib.machinery.SourceFileLoader(module_name, str(SCRIPT_PATH))
    spec = importlib.util.spec_from_loader(module_name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_help_does_not_create_runtime_state(tmp_path):
    runtime_home = tmp_path / "runtime_home"
    env = os.environ.copy()
    env["JTREE_HOME"] = str(runtime_home)
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--help"],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0
    assert "usage:" in result.stdout
    assert not runtime_home.exists()


def test_bootstrap_creates_runtime_state_and_reexecs(monkeypatch, tmp_path):
    module = load_module(monkeypatch, tmp_path / "runtime_home")
    paths = module.build_runtime_paths()
    installs = []

    def fake_create(self, path):
        python_path = path / "bin" / "python"
        python_path.parent.mkdir(parents=True, exist_ok=True)
        python_path.write_text("", encoding="utf-8")

    def fake_install(runtime_paths):
        installs.append(runtime_paths)

    class Reexec(RuntimeError):
        pass

    def fake_execv(executable, argv):
        raise Reexec((executable, tuple(argv)))

    monkeypatch.setattr(module.venv.EnvBuilder, "create", fake_create)
    monkeypatch.setattr(module, "install_runtime_dependencies", fake_install)
    monkeypatch.setattr(module.os, "execv", fake_execv)

    with pytest.raises(Reexec):
        module.ensure_private_venv(paths)

    assert installs == [paths]
    assert paths.bootstrap_state.exists()
    assert paths.venv_python.exists()


def test_bootstrap_rebuilds_when_existing_python_fails_health_check(monkeypatch, tmp_path):
    module = load_module(monkeypatch, tmp_path / "runtime_home")
    paths = module.build_runtime_paths()
    paths.home.mkdir(parents=True, exist_ok=True)
    paths.venv_python.parent.mkdir(parents=True, exist_ok=True)
    paths.venv_python.write_text("", encoding="utf-8")
    paths.bootstrap_state.write_text(
        module.json.dumps(module.desired_bootstrap_state()),
        encoding="utf-8",
    )
    installs = []

    def fake_create(self, path):
        python_path = path / "bin" / "python"
        python_path.parent.mkdir(parents=True, exist_ok=True)
        python_path.write_text("", encoding="utf-8")

    def fake_install(runtime_paths):
        installs.append(runtime_paths)

    class Reexec(RuntimeError):
        pass

    def fake_execv(executable, argv):
        raise Reexec((executable, tuple(argv)))

    monkeypatch.setattr(module.sys, "prefix", str(tmp_path / "outside"))
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: type("Result", (), {"returncode": 134})())
    monkeypatch.setattr(module.venv.EnvBuilder, "create", fake_create)
    monkeypatch.setattr(module, "install_runtime_dependencies", fake_install)
    monkeypatch.setattr(module.os, "execv", fake_execv)

    with pytest.raises(Reexec):
        module.ensure_private_venv(paths)

    assert installs == [paths]
