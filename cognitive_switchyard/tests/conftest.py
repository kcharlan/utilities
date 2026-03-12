from __future__ import annotations

import resource
from pathlib import Path

import pytest

# Raise the soft FD limit so cumulative test resource usage does not
# hit the default macOS cap of 256.
_soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
if _soft < 4096:
    resource.setrlimit(resource.RLIMIT_NOFILE, (min(4096, _hard), _hard))


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]
