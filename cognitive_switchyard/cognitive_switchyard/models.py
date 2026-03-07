from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional


class SessionStatus(str, Enum):
    CREATED = "created"
    PLANNING = "planning"
    RESOLVING = "resolving"
    RUNNING = "running"
    PAUSED = "paused"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    ABORTED = "aborted"


class TaskStatus(str, Enum):
    INTAKE = "intake"
    PLANNING = "planning"
    STAGED = "staged"
    REVIEW = "review"
    READY = "ready"
    ACTIVE = "active"
    DONE = "done"
    BLOCKED = "blocked"


class WorkerStatus(str, Enum):
    IDLE = "idle"
    ACTIVE = "active"
    PROBLEM = "problem"


class EventType(str, Enum):
    SESSION_CREATED = "session_created"
    SESSION_STARTED = "session_started"
    SESSION_PAUSED = "session_paused"
    SESSION_RESUMED = "session_resumed"
    SESSION_COMPLETED = "session_completed"
    SESSION_ABORTED = "session_aborted"
    TASK_STATUS_CHANGE = "task_status_change"
    TASK_DISPATCHED = "task_dispatched"
    TASK_COMPLETED = "task_completed"
    TASK_BLOCKED = "task_blocked"
    WORKER_IDLE = "worker_idle"
    WORKER_ACTIVE = "worker_active"
    VERIFICATION_STARTED = "verification_started"
    VERIFICATION_PASSED = "verification_passed"
    VERIFICATION_FAILED = "verification_failed"
    FIX_STARTED = "fix_started"
    FIX_SUCCEEDED = "fix_succeeded"
    FIX_FAILED = "fix_failed"
    TIMEOUT_WARNING = "timeout_warning"
    TIMEOUT_KILL = "timeout_kill"
    ERROR = "error"


@dataclass
class Session:
    id: str
    name: str
    pack_name: str
    config_json: str
    status: SessionStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    abort_reason: Optional[str] = None


@dataclass
class Task:
    id: str
    session_id: str
    title: str
    status: TaskStatus
    phase: Optional[str] = None
    phase_num: Optional[int] = None
    phase_total: Optional[int] = None
    detail: Optional[str] = None
    worker_slot: Optional[int] = None
    depends_on: list[str] = field(default_factory=list)
    anti_affinity: list[str] = field(default_factory=list)
    exec_order: int = 1
    plan_filename: Optional[str] = None
    blocked_reason: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


@dataclass
class WorkerSlot:
    session_id: str
    slot_number: int
    status: WorkerStatus = WorkerStatus.IDLE
    current_task_id: Optional[str] = None
    pid: Optional[int] = None


@dataclass
class Event:
    session_id: str
    timestamp: datetime
    event_type: EventType
    task_id: Optional[str] = None
    worker_slot: Optional[int] = None
    message: str = ""


@dataclass
class Constraint:
    """Parsed constraint for a single task from resolution.json."""

    task_id: str
    depends_on: list[str] = field(default_factory=list)
    anti_affinity: list[str] = field(default_factory=list)
    exec_order: int = 1


@dataclass
class StatusSidecar:
    """Parsed content of a .status sidecar file."""

    status: str = "blocked"
    commits: str = "none"
    tests_ran: str = "none"
    test_result: str = "skip"
    blocked_reason: str = ""
    notes: str = ""

    @classmethod
    def parse(cls, text: str) -> StatusSidecar:
        result = cls()
        for raw_line in text.strip().splitlines():
            line = raw_line.strip()
            if not line or ":" not in line:
                continue
            key, _, value = line.partition(":")
            key = key.strip().upper()
            value = value.strip()
            if key == "STATUS":
                result.status = value.lower()
            elif key == "COMMITS":
                result.commits = value
            elif key == "TESTS_RAN":
                result.tests_ran = value.lower()
            elif key == "TEST_RESULT":
                result.test_result = value.lower()
            elif key == "BLOCKED_REASON":
                result.blocked_reason = value
            elif key == "NOTES":
                result.notes = value
        return result

    @classmethod
    def from_file(cls, path: str | Path) -> StatusSidecar:
        file_path = Path(path)
        if not file_path.exists():
            return cls()
        try:
            return cls.parse(file_path.read_text())
        except Exception:
            return cls()
