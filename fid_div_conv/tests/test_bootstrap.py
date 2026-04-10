import importlib.machinery
import importlib.util
import uuid
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "fid_div_conv"


def load_module(monkeypatch, runtime_home: Path):
    monkeypatch.setenv("FID_DIV_CONV_HOME", str(runtime_home))
    module_name = f"fid_div_conv_bootstrap_{uuid.uuid4().hex}"
    loader = importlib.machinery.SourceFileLoader(module_name, str(SCRIPT_PATH))
    spec = importlib.util.spec_from_loader(module_name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


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

    class Reexec(RuntimeError):
        pass

    def fake_create(self, path):
        python_path = path / "bin" / "python"
        python_path.parent.mkdir(parents=True, exist_ok=True)
        python_path.write_text("", encoding="utf-8")

    def fake_execv(executable, argv):
        raise Reexec((executable, tuple(argv)))

    monkeypatch.setattr(module.sys, "prefix", str(tmp_path / "outside"))
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: type("Result", (), {"returncode": 134})())
    monkeypatch.setattr(module.venv.EnvBuilder, "create", fake_create)
    monkeypatch.setattr(module.os, "execv", fake_execv)

    with pytest.raises(Reexec):
        module.ensure_private_venv(paths)

