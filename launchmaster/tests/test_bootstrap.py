import importlib.machinery
import importlib.util
import sys
import uuid
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "launchmaster"


def load_module(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["launchmaster", "--help"])
    module_name = f"launchmaster_bootstrap_{uuid.uuid4().hex}"
    loader = importlib.machinery.SourceFileLoader(module_name, str(SCRIPT_PATH))
    spec = importlib.util.spec_from_loader(module_name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    with pytest.raises(SystemExit):
        spec.loader.exec_module(module)
    return module


def test_bootstrap_rebuilds_when_existing_python_fails_health_check(monkeypatch, tmp_path):
    module = load_module(monkeypatch)
    venv_dir = tmp_path / ".launchmaster_venv"
    venv_python = venv_dir / "bin" / "python"
    data_dir = tmp_path / ".launchmaster"
    data_dir.mkdir(parents=True, exist_ok=True)
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.write_text("", encoding="utf-8")
    (data_dir / "bootstrap_state.json").write_text(
        module.json.dumps(module.desired_bootstrap_state()),
        encoding="utf-8",
    )
    events = []

    class Reexec(RuntimeError):
        pass

    def fake_check_call(args):
        events.append(tuple(args))
        if args[:3] == [module.sys.executable, "-m", "venv"]:
            refreshed_python = Path(args[3]) / "bin" / "python"
            refreshed_python.parent.mkdir(parents=True, exist_ok=True)
            refreshed_python.write_text("", encoding="utf-8")

    def fake_execv(executable, argv):
        raise Reexec((executable, tuple(argv)))

    monkeypatch.setattr(module, "VENV_DIR", str(venv_dir))
    monkeypatch.setattr(module, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(module.sys, "prefix", str(tmp_path / "outside"))
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: type("Result", (), {"returncode": 134})())
    monkeypatch.setattr(module.subprocess, "check_call", fake_check_call)
    monkeypatch.setattr(module.os, "execv", fake_execv)

    with pytest.raises(Reexec):
        module.bootstrap()

    assert any(call[:3] == (module.sys.executable, "-m", "venv") for call in events)
    assert any(
        call[:3] == (str(venv_dir / "bin" / "pip"), "install", "--quiet")
        for call in events
    )
    assert venv_python.exists()
    assert (data_dir / "bootstrap_state.json").exists()
