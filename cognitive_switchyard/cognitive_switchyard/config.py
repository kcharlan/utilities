from __future__ import annotations

import socket
from dataclasses import dataclass, field
from pathlib import Path

import yaml

SWITCHYARD_HOME = Path.home() / ".cognitive_switchyard"
SWITCHYARD_VENV = Path.home() / ".cognitive_switchyard_venv"
SWITCHYARD_DB = SWITCHYARD_HOME / "cognitive_switchyard.db"
PACKS_DIR = SWITCHYARD_HOME / "packs"
SESSIONS_DIR = SWITCHYARD_HOME / "sessions"
CONFIG_FILE = SWITCHYARD_HOME / "config.yaml"

BUILTIN_PACKS_DIR = Path(__file__).resolve().parent.parent / "packs"

DEFAULT_POLL_INTERVAL = 5
DEFAULT_MAX_WORKERS = 2
DEFAULT_MAX_PLANNERS = 3
DEFAULT_FULL_TEST_INTERVAL = 4
DEFAULT_TASK_IDLE_TIMEOUT = 300
DEFAULT_TASK_MAX_TIMEOUT = 0
DEFAULT_SESSION_MAX_TIMEOUT = 14400
DEFAULT_MAX_FIX_ATTEMPTS = 2
DEFAULT_RETENTION_DAYS = 30

PROGRESS_PATTERN = "##PROGRESS##"


@dataclass
class GlobalConfig:
    """Global config loaded from ~/.cognitive_switchyard/config.yaml."""

    retention_days: int = DEFAULT_RETENTION_DAYS
    default_planners: int = DEFAULT_MAX_PLANNERS
    default_workers: int = DEFAULT_MAX_WORKERS
    default_pack: str = ""

    @classmethod
    def load(cls) -> GlobalConfig:
        if CONFIG_FILE.exists():
            with CONFIG_FILE.open() as handle:
                data = yaml.safe_load(handle) or {}
            return cls(
                retention_days=data.get("retention_days", DEFAULT_RETENTION_DAYS),
                default_planners=data.get("default_planners", DEFAULT_MAX_PLANNERS),
                default_workers=data.get("default_workers", DEFAULT_MAX_WORKERS),
                default_pack=data.get("default_pack", ""),
            )
        return cls()

    def save(self) -> None:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with CONFIG_FILE.open("w") as handle:
            yaml.safe_dump(
                {
                    "retention_days": self.retention_days,
                    "default_planners": self.default_planners,
                    "default_workers": self.default_workers,
                    "default_pack": self.default_pack,
                },
                handle,
                default_flow_style=False,
            )


@dataclass
class SessionConfig:
    """Per-session configuration stored in SQLite."""

    pack_name: str
    session_name: str
    num_workers: int = DEFAULT_MAX_WORKERS
    num_planners: int = DEFAULT_MAX_PLANNERS
    poll_interval: int = DEFAULT_POLL_INTERVAL
    verification_interval: int = DEFAULT_FULL_TEST_INTERVAL
    auto_fix_enabled: bool = False
    auto_fix_max_attempts: int = DEFAULT_MAX_FIX_ATTEMPTS
    task_idle_timeout: int = DEFAULT_TASK_IDLE_TIMEOUT
    task_max_timeout: int = DEFAULT_TASK_MAX_TIMEOUT
    session_max_timeout: int = DEFAULT_SESSION_MAX_TIMEOUT
    env_vars: dict[str, str] = field(default_factory=dict)


def ensure_directories() -> None:
    for directory in (SWITCHYARD_HOME, PACKS_DIR, SESSIONS_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def session_dir(session_id: str) -> Path:
    return SESSIONS_DIR / session_id


def session_subdirs(session_id: str) -> dict[str, Path]:
    base = session_dir(session_id)
    return {
        "intake": base / "intake",
        "claimed": base / "claimed",
        "staging": base / "staging",
        "review": base / "review",
        "ready": base / "ready",
        "workers": base / "workers",
        "done": base / "done",
        "blocked": base / "blocked",
        "logs": base / "logs",
        "logs_workers": base / "logs" / "workers",
    }


def find_free_port(start_port: int, max_attempts: int = 20) -> int:
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(
        f"No free port found in range {start_port}-{start_port + max_attempts - 1}"
    )
