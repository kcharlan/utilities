"""Root conftest: ensure subproject directories are importable under importlib mode."""
import os
import sys

_ROOT = os.path.dirname(__file__)

# Each subproject directory that contains importable packages used by its tests.
_SUBPROJECT_ROOTS = [
    "cognitive_switchyard",
    "data_format_converter",
    "docker/llm_proxy",
    "docpipe",
    "git-multirepo-dashboard",
    "harscope",
    "jtree",
    "llm_proxy",
    "llm_proxy/src",
    "mls-tracker",
    "tax2",
]

for _sub in _SUBPROJECT_ROOTS:
    _path = os.path.join(_ROOT, _sub)
    if os.path.isdir(_path) and _path not in sys.path:
        sys.path.insert(0, _path)
