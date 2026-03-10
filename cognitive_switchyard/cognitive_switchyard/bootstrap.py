from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import venv
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from .config import GlobalConfig, build_runtime_paths, ensure_global_config


BOOTSTRAP_OPTION_FLAGS = {"--runtime-root", "--builtin-packs-root"}
COMMANDS_REQUIRING_BOOTSTRAP = {
    "packs",
    "sync-packs",
    "reset-pack",
    "reset-all-packs",
    "start",
    "serve",
}
DEFAULT_DEPENDENCY_MODULES = ("yaml", "fastapi", "uvicorn")


class BootstrapRequired(RuntimeError):
    def __init__(self, *, python_executable: Path, argv: Sequence[str]) -> None:
        self.python_executable = python_executable
        self.argv = tuple(argv)
        super().__init__(f"Re-exec required via {python_executable}")


@dataclass(frozen=True)
class BootstrapSettings:
    repo_root: Path
    runtime_paths: object
    builtin_packs_root: Path | None = None
    dependency_modules: tuple[str, ...] = DEFAULT_DEPENDENCY_MODULES


def default_bootstrap_settings(
    *,
    runtime_root: Path | None = None,
    builtin_packs_root: Path | None = None,
) -> BootstrapSettings:
    repo_root = Path(__file__).resolve().parents[1]
    runtime_paths = build_runtime_paths(home=runtime_root)
    return BootstrapSettings(
        repo_root=repo_root,
        runtime_paths=runtime_paths,
        builtin_packs_root=builtin_packs_root or repo_root / "cognitive_switchyard" / "builtin_packs",
    )


def command_needs_bootstrap(argv: Sequence[str]) -> bool:
    if not argv:
        return False
    if any(arg in {"-h", "--help"} for arg in argv):
        return False
    index = 0
    while index < len(argv):
        current = argv[index]
        if current in BOOTSTRAP_OPTION_FLAGS:
            index += 2
            continue
        if current.startswith("-"):
            index += 1
            continue
        return current in COMMANDS_REQUIRING_BOOTSTRAP
    return False


def bootstrap_if_needed(
    argv: Sequence[str],
    *,
    settings: BootstrapSettings | None = None,
    dependency_probe: Callable[[str], bool] | None = None,
    create_venv: Callable[[Path], None] | None = None,
    install_requirements: Callable[[Path], None] | None = None,
    reexec: Callable[[Path, list[str]], None] | None = None,
) -> bool:
    if not command_needs_bootstrap(argv):
        return False

    settings = settings or default_bootstrap_settings()
    dependency_probe = dependency_probe or _dependency_is_available
    create_venv = create_venv or _create_bootstrap_venv
    install_requirements = install_requirements or _make_install_requirements(settings.repo_root)
    reexec = reexec or _default_reexec

    if all(dependency_probe(module_name) for module_name in settings.dependency_modules):
        return False

    create_venv(settings.runtime_paths.bootstrap_venv)
    python_executable = settings.runtime_paths.bootstrap_venv / "bin" / "python"
    install_requirements(python_executable)
    reexec(python_executable, list(argv))
    return True


def initialize_runtime_environment(settings: BootstrapSettings) -> GlobalConfig:
    from .pack_loader import list_builtin_pack_names, sync_builtin_packs

    runtime_paths = settings.runtime_paths
    runtime_paths.home.mkdir(parents=True, exist_ok=True)
    runtime_paths.packs.mkdir(parents=True, exist_ok=True)
    runtime_paths.sessions.mkdir(parents=True, exist_ok=True)

    builtin_root = settings.builtin_packs_root or default_bootstrap_settings().builtin_packs_root
    builtin_names = list_builtin_pack_names(builtin_root)
    default_pack = "claude-code" if "claude-code" in builtin_names else (
        builtin_names[0] if builtin_names else "claude-code"
    )
    config = ensure_global_config(runtime_paths.config, default_pack=default_pack)
    sync_builtin_packs(
        builtin_packs_root=builtin_root,
        runtime_packs_dir=runtime_paths.packs,
    )
    return config


def _dependency_is_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _create_bootstrap_venv(path: Path) -> None:
    if path.exists():
        return
    venv.EnvBuilder(with_pip=True).create(path)


def _make_install_requirements(repo_root: Path) -> Callable[[Path], None]:
    requirements_path = repo_root / "requirements.txt"

    def _install(python_executable: Path) -> None:
        subprocess.run(
            [str(python_executable), "-m", "pip", "install", "-r", str(requirements_path)],
            check=True,
        )

    return _install


def _default_reexec(python_executable: Path, argv: list[str]) -> None:
    os.execv(
        str(python_executable),
        [str(python_executable), "-m", "cognitive_switchyard", *argv],
    )


def derive_bootstrap_settings(argv: Sequence[str]) -> BootstrapSettings:
    runtime_root: Path | None = None
    builtin_packs_root: Path | None = None
    index = 0
    while index < len(argv):
        current = argv[index]
        if current == "--runtime-root" and index + 1 < len(argv):
            runtime_root = Path(argv[index + 1]).expanduser()
            index += 2
            continue
        if current == "--builtin-packs-root" and index + 1 < len(argv):
            builtin_packs_root = Path(argv[index + 1]).expanduser()
            index += 2
            continue
        index += 1
    return default_bootstrap_settings(
        runtime_root=runtime_root,
        builtin_packs_root=builtin_packs_root,
    )
