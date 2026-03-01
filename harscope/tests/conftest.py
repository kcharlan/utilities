"""Shared fixtures for harscope API tests.

The main harscope file has no .py extension, so we import it via importlib
and expose the FastAPI ``app`` plus helper classes through fixtures.
"""

import importlib.machinery
import importlib.util
import json
import os
import sys

import pytest
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Import the extensionless ``harscope`` script as a Python module
# ---------------------------------------------------------------------------
_HARSCOPE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'harscope'))

# The file has no .py extension, so we must create the loader manually.
_loader = importlib.machinery.SourceFileLoader('harscope_mod', _HARSCOPE_PATH)
_spec = importlib.util.spec_from_file_location(
    'harscope_mod', _HARSCOPE_PATH, loader=_loader,
    submodule_search_locations=[],
)
harscope_mod = importlib.util.module_from_spec(_spec)

# Prevent the bootstrap() / __main__ block from running
harscope_mod.__name__ = 'harscope_mod'
sys.modules['harscope_mod'] = harscope_mod
_spec.loader.exec_module(harscope_mod)

# Re-export for direct import in test files
app = harscope_mod.app
HARManager = harscope_mod.HARManager
SecurityScanner = harscope_mod.SecurityScanner
ExportEngine = harscope_mod.ExportEngine

# ---------------------------------------------------------------------------
# Minimal valid HAR content used across many tests
# ---------------------------------------------------------------------------
MINIMAL_HAR = {
    "log": {
        "version": "1.2",
        "creator": {"name": "test", "version": "1.0"},
        "entries": [
            {
                "startedDateTime": "2024-01-01T00:00:00.000Z",
                "time": 100,
                "request": {
                    "method": "GET",
                    "url": "https://example.com/api/data",
                    "httpVersion": "HTTP/1.1",
                    "headers": [
                        {"name": "Host", "value": "example.com"},
                        {"name": "Authorization", "value": "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123def456"},
                    ],
                    "queryString": [
                        {"name": "api_key", "value": "sk-proj-abc123def456ghi789jkl012mno345"},
                    ],
                    "cookies": [],
                    "headersSize": -1,
                    "bodySize": -1,
                },
                "response": {
                    "status": 200,
                    "statusText": "OK",
                    "httpVersion": "HTTP/1.1",
                    "headers": [
                        {"name": "Content-Type", "value": "application/json"},
                        {"name": "Set-Cookie", "value": "session=abc123xyz; Path=/; HttpOnly"},
                    ],
                    "cookies": [
                        {"name": "session_token", "value": "abc123xyz789def456ghi012jkl345mno678pqr901stu234vwx567"},
                    ],
                    "content": {
                        "size": 50,
                        "mimeType": "application/json",
                        "text": '{"user":"alice","token":"eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123def456","status":"ok"}',
                    },
                    "redirectURL": "",
                    "headersSize": -1,
                    "bodySize": 50,
                },
                "cache": {},
                "timings": {
                    "blocked": 1,
                    "dns": 5,
                    "connect": 10,
                    "ssl": 8,
                    "send": 2,
                    "wait": 60,
                    "receive": 14,
                },
            },
            {
                "startedDateTime": "2024-01-01T00:00:00.200Z",
                "time": 50,
                "request": {
                    "method": "POST",
                    "url": "http://example.com/api/submit",
                    "httpVersion": "HTTP/1.1",
                    "headers": [
                        {"name": "Content-Type", "value": "application/json"},
                    ],
                    "queryString": [],
                    "cookies": [],
                    "headersSize": -1,
                    "bodySize": 30,
                    "postData": {
                        "mimeType": "application/json",
                        "text": '{"username":"bob","password":"s3cret!","action":"login"}',
                    },
                },
                "response": {
                    "status": 401,
                    "statusText": "Unauthorized",
                    "httpVersion": "HTTP/1.1",
                    "headers": [
                        {"name": "Content-Type", "value": "application/json"},
                    ],
                    "cookies": [],
                    "content": {
                        "size": 30,
                        "mimeType": "application/json",
                        "text": '{"error":"Invalid credentials"}',
                    },
                    "redirectURL": "",
                    "headersSize": -1,
                    "bodySize": 30,
                },
                "cache": {},
                "timings": {
                    "blocked": 0,
                    "dns": 0,
                    "connect": 0,
                    "ssl": 0,
                    "send": 1,
                    "wait": 45,
                    "receive": 4,
                },
            },
        ],
    }
}


def _reset_global_state():
    """Reset the module-level singletons so tests don't leak state."""
    harscope_mod.har_manager.__init__()
    harscope_mod.security_scanner.__init__()
    harscope_mod.sequence_builder.__init__()


@pytest.fixture(autouse=True)
def _isolate_state():
    """Ensure every test starts with a clean slate."""
    _reset_global_state()
    yield
    _reset_global_state()


@pytest.fixture
def client():
    """Synchronous-style test client using httpx."""
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def minimal_har_json():
    """Return the minimal HAR content as a JSON string."""
    return json.dumps(MINIMAL_HAR)


@pytest.fixture
def minimal_har_dict():
    """Return the minimal HAR content as a dict (deep copy)."""
    import copy
    return copy.deepcopy(MINIMAL_HAR)


async def load_har(client: AsyncClient, har_dict: dict = None, filename: str = "test.har"):
    """Helper: load a HAR into the server via /api/open-content."""
    content = json.dumps(har_dict or MINIMAL_HAR)
    resp = await client.post("/api/open-content", json={"content": content, "filename": filename})
    assert resp.status_code == 200, f"Failed to load HAR: {resp.text}"
    return resp.json()
