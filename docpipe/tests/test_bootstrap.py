import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "docpipe"


def load_module(monkeypatch, runtime_home: Path):
    monkeypatch.setenv("DOCPIPE_HOME", str(runtime_home))
    module_name = f"docpipe_bootstrap_{uuid.uuid4().hex}"
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
    env["DOCPIPE_HOME"] = str(runtime_home)
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "convert", "--help"],
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

    def fake_run(args, check=True):
        if args[:3] == [sys.executable, "-m", "venv"]:
            python_path = paths.venv_python
            python_path.parent.mkdir(parents=True, exist_ok=True)
            python_path.write_text("", encoding="utf-8")
        elif args[:4] == [str(paths.venv_python), "-m", "pip", "install"]:
            installs.append(tuple(args))
        return None

    class Reexec(RuntimeError):
        pass

    def fake_execv(executable, argv):
        raise Reexec((executable, tuple(argv)))

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module.os, "execv", fake_execv)

    with pytest.raises(Reexec):
        module.ensure_private_venv(paths)

    assert installs
    assert paths.bootstrap_state.exists()
    assert paths.venv_python.exists()
