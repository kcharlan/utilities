"""Root conftest: make the extensionless mls_tracker script importable."""
import importlib.util
import sys
from pathlib import Path

_script = Path(__file__).resolve().parent / "mls_tracker"
_loader = importlib.machinery.SourceFileLoader("mls_tracker", str(_script))
_spec = importlib.util.spec_from_loader("mls_tracker", _loader, origin=str(_script))
_mod = importlib.util.module_from_spec(_spec)
_mod.__name__ = "mls_tracker"
sys.modules["mls_tracker"] = _mod
_spec.loader.exec_module(_mod)
