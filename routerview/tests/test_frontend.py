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
    python_multipart.__all__ = []
    multipart_submodule = ModuleType("python_multipart.multipart")
    multipart_submodule.parse_options_header = lambda value: (value, {})
    monkeypatch.setitem(sys.modules, "python_multipart", python_multipart)
    monkeypatch.setitem(sys.modules, "python_multipart.multipart", multipart_submodule)
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


def test_chart_tooltip_sorts_cost_rows_descending(monkeypatch):
    module = load_module(monkeypatch)

    assert "function sortTooltipItems(items, metric)" in module.HTML_TEMPLATE
    assert "if(metric!=='cost') return items;" in module.HTML_TEMPLATE
    assert "return [...items].sort((a,b)=>(Number(b?.value)||0)-(Number(a?.value)||0));" in module.HTML_TEMPLATE
    assert "const orderedPrimary = sortTooltipItems(primary, metric);" in module.HTML_TEMPLATE
    assert "const orderedComp = sortTooltipItems(comp, metric);" in module.HTML_TEMPLATE


def test_csv_import_triggers_dashboard_refresh(monkeypatch):
    module = load_module(monkeypatch)

    assert "function SettingsPanel({onClose,onImportComplete})" in module.HTML_TEMPLATE
    assert "if(d.status==='ok') onImportComplete?.();" in module.HTML_TEMPLATE
    assert "<SettingsPanel onClose={()=>setShowSettings(false)} onImportComplete={()=>{fetchData();fetchLog();}}/>" in module.HTML_TEMPLATE


def test_frontend_removes_live_observability_controls(monkeypatch):
    module = load_module(monkeypatch)

    assert "Fetch from API" not in module.HTML_TEMPLATE
    assert "function SetupWizard(" not in module.HTML_TEMPLATE
    assert "new WebSocket(" not in module.HTML_TEMPLATE
    assert "wsConnected?'Live':'Disconnected'" not in module.HTML_TEMPLATE


def test_header_shows_selected_preset_with_resolved_range(monkeypatch):
    module = load_module(monkeypatch)

    assert "function formatResolvedRange(fromIso,toIso,tz)" in module.HTML_TEMPLATE
    assert "const activeRangeLabel = RANGE_OPTS.find(o=>o.v===timeRange)?.l||'Custom Range';" in module.HTML_TEMPLATE
    assert "const resolvedRange = summary?.from&&summary?.to ? formatResolvedRange(summary.from, summary.to, tz) : null;" in module.HTML_TEMPLATE
    assert "<Header" in module.HTML_TEMPLATE
    assert "summary={summary}" in module.HTML_TEMPLATE
