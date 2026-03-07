#!/usr/bin/env python3
from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VENV_DIR = Path.home() / ".cognitive_switchyard_venv"
REQUIREMENTS_FILE = PROJECT_ROOT / "requirements.txt"
DEPENDENCIES = ["fastapi", "uvicorn", "aiosqlite", "pyyaml"]
IMPORT_CHECKS = ["fastapi", "uvicorn", "aiosqlite", "yaml"]


def bootstrap() -> None:
    """Ensure runtime dependencies are available before loading the CLI."""
    if sys.prefix == str(VENV_DIR):
        return

    try:
        for name in IMPORT_CHECKS:
            importlib.import_module(name)
        return
    except ImportError:
        pass

    venv_python = VENV_DIR / "bin" / "python3"
    if venv_python.exists():
        os.execv(
            str(venv_python),
            [str(venv_python), "-m", "cognitive_switchyard", *sys.argv[1:]],
        )

    print(f"First run: creating virtual environment at {VENV_DIR}")
    subprocess.check_call([sys.executable, "-m", "venv", str(VENV_DIR)])

    pip = VENV_DIR / "bin" / "pip"
    if REQUIREMENTS_FILE.exists():
        print(f"Installing dependencies from {REQUIREMENTS_FILE}")
        subprocess.check_call([str(pip), "install", "--quiet", "-r", str(REQUIREMENTS_FILE)])
    else:
        print(f"Installing dependencies: {', '.join(DEPENDENCIES)}")
        subprocess.check_call([str(pip), "install", "--quiet", *DEPENDENCIES])

    print("Setup complete. Starting Cognitive Switchyard...\n")
    os.execv(
        str(venv_python),
        [str(venv_python), "-m", "cognitive_switchyard", *sys.argv[1:]],
    )


def main() -> None:
    bootstrap()
    from cognitive_switchyard.cli import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()
