import importlib.machinery
import importlib.util
import sys
import uuid
import webbrowser
from pathlib import Path
from types import ModuleType


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "routerview"


def load_module(monkeypatch):
    python_multipart = ModuleType("python_multipart")
    python_multipart.__version__ = "0.0.20"
    monkeypatch.setitem(sys.modules, "python_multipart", python_multipart)
    module_name = f"routerview_startup_{uuid.uuid4().hex}"
    loader = importlib.machinery.SourceFileLoader(module_name, str(SCRIPT_PATH))
    spec = importlib.util.spec_from_loader(module_name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_announce_resolved_port_reports_fallback(monkeypatch, capsys):
    module = load_module(monkeypatch)

    module.announce_resolved_port(8100, 8101)

    out = capsys.readouterr().out
    assert "Port 8100 is in use; using port 8101 instead." in out


def test_announce_resolved_port_quiet_when_unchanged(monkeypatch, capsys):
    module = load_module(monkeypatch)

    module.announce_resolved_port(8100, 8100)

    assert capsys.readouterr().out == ""


def test_open_browser_when_ready_waits_for_health(monkeypatch):
    module = load_module(monkeypatch)
    attempts = []
    opened = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def getcode(self):
            return self.status

    def fake_urlopen(url, timeout):
        attempts.append((url, timeout))
        if len(attempts) < 3:
            raise module.urllib.error.URLError("not ready")
        return FakeResponse()

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    monkeypatch.setattr(webbrowser, "open", opened.append)

    module.open_browser_when_ready("http://127.0.0.1:8102", timeout_seconds=1.0)

    assert attempts[0][0] == "http://127.0.0.1:8102/api/health"
    assert opened == ["http://127.0.0.1:8102"]
