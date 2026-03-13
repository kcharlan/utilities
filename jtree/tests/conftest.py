"""Shared fixtures for jtree API tests."""
import importlib.util
import importlib.machinery
import json
import os
import sys

import pytest

os.environ.setdefault("UTILITIES_TESTING", "1")

# ---------------------------------------------------------------------------
# Import the extensionless 'jtree' script as a module without triggering
# its __main__ bootstrap.  We use SourceFileLoader explicitly because
# spec_from_file_location returns None for extensionless files.
# ---------------------------------------------------------------------------
_JTREE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, "jtree"))
_loader = importlib.machinery.SourceFileLoader("jtree_mod", _JTREE_PATH)
_spec = importlib.util.spec_from_loader("jtree_mod", _loader, origin=_JTREE_PATH)
jtree_mod = importlib.util.module_from_spec(_spec)
# Prevent the if __name__ == "__main__" block from running
jtree_mod.__name__ = "jtree_mod"
sys.modules["jtree_mod"] = jtree_mod
_spec.loader.exec_module(jtree_mod)

# Re-export handy references
app = jtree_mod.app
JSONManager = jtree_mod.JSONManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_DATA = {
    "name": "jtree",
    "version": 1,
    "tags": ["json", "viewer", "editor"],
    "nested": {
        "a": 1,
        "b": [10, 20, 30],
        "c": {"deep": True}
    },
    "empty_obj": {},
    "empty_arr": [],
    "flag": False,
    "nothing": None,
}


@pytest.fixture()
def sample_json_file(tmp_path):
    """Write SAMPLE_DATA to a temp .json file and return its path."""
    p = tmp_path / "sample.json"
    p.write_text(json.dumps(SAMPLE_DATA, indent=2))
    return str(p)


@pytest.fixture()
def readonly_json_file(tmp_path):
    """Write SAMPLE_DATA to a temp .json file for readonly tests."""
    p = tmp_path / "readonly.json"
    p.write_text(json.dumps(SAMPLE_DATA, indent=2))
    return str(p)


@pytest.fixture(autouse=True)
def _reset_manager():
    """Reset the global json_manager before every test to avoid cross-test leakage."""
    jtree_mod.json_manager = None
    yield
    jtree_mod.json_manager = None


@pytest.fixture()
def client():
    """Synchronous HTTPX TestClient wrapping the FastAPI app."""
    from starlette.testclient import TestClient
    return TestClient(app)


@pytest.fixture()
def loaded_client(client, sample_json_file):
    """A TestClient with a file already loaded via /api/open."""
    resp = client.post("/api/open", json={"path": sample_json_file})
    assert resp.status_code == 200
    return client


@pytest.fixture()
def readonly_client(client, readonly_json_file):
    """A TestClient with a file loaded in readonly mode."""
    resp = client.post("/api/open", json={"path": readonly_json_file, "readonly": True})
    assert resp.status_code == 200
    return client
