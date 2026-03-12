from __future__ import annotations

import importlib.util
import resource
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Auto-sync dev venv with requirements files
# ---------------------------------------------------------------------------
# When requirements.txt or requirements-dev.txt gain new packages, the dev
# venv can silently fall behind.  Rather than letting tests hang or fail with
# cryptic import errors, detect missing packages at collection time and
# install them automatically — mirroring the production bootstrap approach.

_REPO_ROOT = Path(__file__).resolve().parents[1]

# pip package name → Python import name (only for cases where they differ)
_IMPORT_NAME_OVERRIDES: dict[str, str] = {
    "PyYAML": "yaml",
    "pytest-playwright": "pytest_playwright",
}


def _parse_requirements(path: Path) -> list[str]:
    """Return package names from a requirements file, skipping -r includes and blanks."""
    if not path.is_file():
        return []
    packages: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        # Strip version specifiers (e.g. "uvicorn>=0.20" → "uvicorn")
        for sep in (">=", "<=", "==", "!=", "~=", ">", "<", "["):
            idx = line.find(sep)
            if idx != -1:
                line = line[:idx]
        packages.append(line.strip())
    return packages


def _import_name(package: str) -> str:
    """Derive the importable module name for a pip package."""
    if package in _IMPORT_NAME_OVERRIDES:
        return _IMPORT_NAME_OVERRIDES[package]
    return package.lower().replace("-", "_")


def _sync_dev_dependencies() -> None:
    all_packages: list[str] = []
    all_packages.extend(_parse_requirements(_REPO_ROOT / "requirements.txt"))
    all_packages.extend(_parse_requirements(_REPO_ROOT / "requirements-dev.txt"))

    missing = [
        pkg for pkg in all_packages
        if importlib.util.find_spec(_import_name(pkg)) is None
    ]
    if not missing:
        return

    print(
        f"\n[conftest] Dev venv is stale — installing {len(missing)} missing "
        f"package(s): {', '.join(missing)}",
        file=sys.stderr,
    )
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", *missing],
        capture_output=True,
    )
    if result.returncode != 0:
        stderr_text = result.stderr.decode(errors="replace") if result.stderr else ""
        pytest.exit(
            f"Failed to auto-install missing dev dependencies ({', '.join(missing)}).\n"
            f"Run manually: pip install {' '.join(missing)}\n{stderr_text}",
            returncode=1,
        )
    # Verify the installs took effect
    still_missing = [
        pkg for pkg in missing
        if importlib.util.find_spec(_import_name(pkg)) is None
    ]
    if still_missing:
        pytest.exit(
            f"Installed packages but still cannot import: {', '.join(still_missing)}.\n"
            f"Check _IMPORT_NAME_OVERRIDES in conftest.py if the import name differs from the pip name.",
            returncode=1,
        )


_sync_dev_dependencies()

# ---------------------------------------------------------------------------
# Raise the soft FD limit so cumulative test resource usage does not
# hit the default macOS cap of 256.
_soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
if _soft < 4096:
    resource.setrlimit(resource.RLIMIT_NOFILE, (min(4096, _hard), _hard))


@pytest.fixture
def repo_root() -> Path:
    return _REPO_ROOT
