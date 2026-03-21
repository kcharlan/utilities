import importlib.machinery
import importlib.util
import sys
import uuid
from pathlib import Path
from types import ModuleType


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "routerview"


def load_module(monkeypatch):
    python_multipart = ModuleType("python_multipart")
    python_multipart.__version__ = "0.0.20"
    monkeypatch.setitem(sys.modules, "python_multipart", python_multipart)
    module_name = f"routerview_frontend_{uuid.uuid4().hex}"
    loader = importlib.machinery.SourceFileLoader(module_name, str(SCRIPT_PATH))
    spec = importlib.util.spec_from_loader(module_name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_chart_tooltip_includes_bucket_totals_for_additive_metrics(monkeypatch):
    module = load_module(monkeypatch)

    assert "function sumTooltipValues(items)" in module.HTML_TEMPLATE
    assert "const showTotals = metric!=='latency';" in module.HTML_TEMPLATE
    assert "const primaryTotal = sumTooltipValues(primary);" in module.HTML_TEMPLATE
    assert "const compTotal = sumTooltipValues(comp);" in module.HTML_TEMPLATE
    assert '<span className="font-medium text-slate-300">Total</span>' in module.HTML_TEMPLATE
