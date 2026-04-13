import importlib.machinery
import importlib.util
import sqlite3
import sys
import uuid
from pathlib import Path
from types import ModuleType

from fastapi.testclient import TestClient


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "routerview"


def load_module(monkeypatch, runtime_home: Path):
    monkeypatch.setenv("ROUTERVIEW_HOME", str(runtime_home))
    python_multipart = ModuleType("python_multipart")
    python_multipart.__version__ = "0.0.20"
    monkeypatch.setitem(sys.modules, "python_multipart", python_multipart)
    module_name = f"routerview_csv_{uuid.uuid4().hex}"
    loader = importlib.machinery.SourceFileLoader(module_name, str(SCRIPT_PATH))
    spec = importlib.util.spec_from_loader(module_name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def build_client(module, monkeypatch, tmp_path: Path):
    db_path = tmp_path / "routerview.db"
    module.init_database(str(db_path))
    module._db_path = str(db_path)

    return TestClient(module.app), db_path


def test_csv_import_reimport_counts_duplicates_as_skipped(monkeypatch, tmp_path):
    module = load_module(monkeypatch, tmp_path / "runtime_home")
    client, db_path = build_client(module, monkeypatch, tmp_path)
    csv_text = """generation_id,created_at,model_permaslug,provider_name,api_key_name,app_name,tokens_prompt,tokens_completion,tokens_reasoning,tokens_cached,cost_total,cost_cache,cost_web_search,cost_file_processing,generation_time_ms,finish_reason_normalized,streamed,cancelled,num_search_results,user,time_to_first_token_ms
gen-a,2026-04-13T10:00:00Z,openai/gpt-4o-mini,OpenAI,Primary,Test App,10,20,3,1,0.12,0.01,0.00,0.00,123,stop,true,false,0,user-1,50
gen-b,2026-04-13T11:00:00Z,anthropic/claude-3.7-sonnet,Anthropic,Primary,Test App,15,25,4,2,0.34,0.02,0.00,0.00,234,stop,false,false,1,user-2,80
"""

    first = client.post(
        "/api/import/csv",
        files={"file": ("openrouter_activity.csv", csv_text, "text/csv")},
    )
    assert first.status_code == 200
    assert first.json() == {"status": "ok", "inserted": 2, "skipped": 0}

    second = client.post(
        "/api/import/csv",
        files={"file": ("openrouter_activity.csv", csv_text, "text/csv")},
    )
    assert second.status_code == 200
    assert second.json() == {"status": "ok", "inserted": 0, "skipped": 2}

    conn = sqlite3.connect(db_path)
    try:
        total = conn.execute("SELECT COUNT(*) FROM generations").fetchone()[0]
    finally:
        conn.close()
    assert total == 2


def test_csv_import_uses_client_timezone_for_naive_timestamps(monkeypatch, tmp_path):
    module = load_module(monkeypatch, tmp_path / "runtime_home")
    client, _ = build_client(module, monkeypatch, tmp_path)
    csv_text = """generation_id,created_at,model_permaslug,provider_name,api_key_name,app_name,tokens_prompt,tokens_completion,tokens_reasoning,tokens_cached,cost_total,cost_cache,cost_web_search,cost_file_processing,generation_time_ms,finish_reason_normalized,streamed,cancelled,num_search_results,user,time_to_first_token_ms
gen-tz,2026-04-13 14:15:00,openai/gpt-5.4-mini-20260317,OpenAI,Primary,Test App,10,20,3,1,0.12,0.01,0.00,0.00,123,stop,true,false,0,user-1,50
"""

    imported = client.post(
        "/api/import/csv",
        data={"tz": "America/New_York"},
        files={"file": ("openrouter_activity.csv", csv_text, "text/csv")},
    )
    assert imported.status_code == 200
    assert imported.json() == {"status": "ok", "inserted": 1, "skipped": 0}

    timeseries = client.get(
        "/api/timeseries",
        params={
            "from": "2026-04-13T00:00:00-04:00",
            "to": "2026-04-13T23:59:59-04:00",
            "tz": "America/New_York",
            "metric": "cost",
            "group_by": "model",
        },
    )
    assert timeseries.status_code == 200
    payload = timeseries.json()
    bucket_index = payload["buckets"].index("2026-04-13T14:00")
    assert payload["series"][0]["data"][bucket_index] == 0.12
