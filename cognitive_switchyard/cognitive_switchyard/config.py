from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


_SESSION_SUBDIRS = (
    "intake",
    "claimed",
    "staging",
    "review",
    "ready",
    "workers",
    "done",
    "blocked",
    "logs",
    "logs/workers",
)


@dataclass(frozen=True)
class RuntimePaths:
    home: Path
    bootstrap_venv: Path
    database: Path
    config: Path
    packs: Path
    sessions: Path

    def session(self, session_id: str) -> Path:
        return self.sessions / session_id

    def session_paths(self, session_id: str) -> "SessionPaths":
        root = self.session(session_id)
        return SessionPaths(
            root=root,
            intake=root / "intake",
            claimed=root / "claimed",
            staging=root / "staging",
            review=root / "review",
            ready=root / "ready",
            workers=root / "workers",
            done=root / "done",
            blocked=root / "blocked",
            logs=root / "logs",
            worker_logs=root / "logs" / "workers",
            resolution=root / "resolution.json",
            session_log=root / "logs" / "session.log",
            verify_log=root / "logs" / "verify.log",
        )


@dataclass(frozen=True)
class SessionPaths:
    root: Path
    intake: Path
    claimed: Path
    staging: Path
    review: Path
    ready: Path
    workers: Path
    done: Path
    blocked: Path
    logs: Path
    worker_logs: Path
    resolution: Path
    session_log: Path
    verify_log: Path

    def worker_dir(self, slot: int) -> Path:
        return self.workers / str(slot)

    def worker_log(self, slot: int) -> Path:
        return self.worker_logs / f"{slot}.log"

    def worker_recovery_path(self, slot: int) -> Path:
        return self.worker_dir(slot) / "recovery.json"

    def plan_path(
        self, task_id: str, *, status: str, worker_slot: int | None = None
    ) -> Path:
        directory = self._status_directory(status, worker_slot=worker_slot)
        return directory / f"{task_id}.plan.md"

    def materialize(self) -> None:
        for subdir in session_subdirs():
            (self.root / subdir).mkdir(parents=True, exist_ok=True)

    def _status_directory(self, status: str, *, worker_slot: int | None) -> Path:
        directories = {
            "intake": self.intake,
            "planning": self.claimed,
            "staged": self.staging,
            "review": self.review,
            "ready": self.ready,
            "done": self.done,
            "blocked": self.blocked,
        }
        if status == "active":
            if worker_slot is None:
                raise ValueError("worker_slot is required when status is active")
            return self.worker_dir(worker_slot)
        try:
            return directories[status]
        except KeyError as exc:
            raise ValueError(f"Unsupported task status: {status}") from exc


def build_runtime_paths(home: Path | None = None) -> RuntimePaths:
    user_home = home if home is not None else Path.home()
    runtime_home = user_home / ".cognitive_switchyard"
    return RuntimePaths(
        home=runtime_home,
        bootstrap_venv=user_home / ".cognitive_switchyard_venv",
        database=runtime_home / "cognitive_switchyard.db",
        config=runtime_home / "config.yaml",
        packs=runtime_home / "packs",
        sessions=runtime_home / "sessions",
    )


def session_subdirs() -> tuple[str, ...]:
    return _SESSION_SUBDIRS


def canonical_pack_path(pack_name: str, relative_path: str | None = None) -> str:
    base = f"~/.cognitive_switchyard/packs/{pack_name}"
    if not relative_path:
        return base
    return f"{base}/{relative_path}"
