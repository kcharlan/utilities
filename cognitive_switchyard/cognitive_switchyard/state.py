from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

import cognitive_switchyard.config as config
from cognitive_switchyard.models import (
    Event,
    EventType,
    Session,
    SessionStatus,
    Task,
    TaskStatus,
    WorkerSlot,
    WorkerStatus,
)

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    pack_name TEXT NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'created',
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    abort_reason TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'intake',
    phase TEXT,
    phase_num INTEGER,
    phase_total INTEGER,
    detail TEXT,
    worker_slot INTEGER,
    depends_on TEXT NOT NULL DEFAULT '[]',
    anti_affinity TEXT NOT NULL DEFAULT '[]',
    exec_order INTEGER NOT NULL DEFAULT 1,
    plan_filename TEXT,
    blocked_reason TEXT,
    created_at TEXT,
    started_at TEXT,
    completed_at TEXT,
    PRIMARY KEY (id, session_id),
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS worker_slots (
    session_id TEXT NOT NULL,
    slot_number INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'idle',
    current_task_id TEXT,
    pid INTEGER,
    PRIMARY KEY (session_id, slot_number),
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    task_id TEXT,
    worker_slot INTEGER,
    message TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);
"""


class StateStore:
    """Synchronous SQLite state store for the orchestrator."""

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path or config.SWITCHYARD_DB
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self) -> None:
        self._conn = sqlite3.connect(str(self._db_path), timeout=10)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("StateStore not connected. Call connect() first.")
        return self._conn

    def create_session(self, session: Session) -> None:
        self.conn.execute(
            """
            INSERT INTO sessions (id, name, pack_name, config_json, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session.id,
                session.name,
                session.pack_name,
                session.config_json,
                session.status.value,
                session.created_at.isoformat(),
            ),
        )
        self.conn.commit()

    def get_session(self, session_id: str) -> Optional[Session]:
        row = self.conn.execute(
            "SELECT * FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        return self._row_to_session(row) if row else None

    def list_sessions(self) -> list[Session]:
        rows = self.conn.execute(
            "SELECT * FROM sessions ORDER BY created_at DESC"
        ).fetchall()
        return [self._row_to_session(row) for row in rows]

    def update_session_status(
        self,
        session_id: str,
        new_status: SessionStatus,
        expected_status: Optional[SessionStatus] = None,
        **extra_fields,
    ) -> bool:
        set_parts = ["status = ?"]
        params: list[object] = [new_status.value]
        for key, value in extra_fields.items():
            if key in {"started_at", "completed_at"}:
                set_parts.append(f"{key} = ?")
                params.append(value.isoformat() if isinstance(value, datetime) else value)
            elif key == "abort_reason":
                set_parts.append(f"{key} = ?")
                params.append(value)

        where = "id = ?"
        params.append(session_id)
        if expected_status is not None:
            where += " AND status = ?"
            params.append(expected_status.value)

        cursor = self.conn.execute(
            f"UPDATE sessions SET {', '.join(set_parts)} WHERE {where}",
            params,
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def delete_session(self, session_id: str) -> bool:
        self.conn.execute("DELETE FROM events WHERE session_id = ?", (session_id,))
        self.conn.execute("DELETE FROM worker_slots WHERE session_id = ?", (session_id,))
        self.conn.execute("DELETE FROM tasks WHERE session_id = ?", (session_id,))
        cursor = self.conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def create_task(self, task: Task) -> None:
        self.conn.execute(
            """
            INSERT INTO tasks (
                id, session_id, title, status, depends_on, anti_affinity,
                exec_order, plan_filename, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task.id,
                task.session_id,
                task.title,
                task.status.value,
                json.dumps(task.depends_on),
                json.dumps(task.anti_affinity),
                task.exec_order,
                task.plan_filename,
                task.created_at.isoformat() if task.created_at else None,
            ),
        )
        self.conn.commit()

    def get_task(self, session_id: str, task_id: str) -> Optional[Task]:
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE session_id = ? AND id = ?",
            (session_id, task_id),
        ).fetchone()
        return self._row_to_task(row) if row else None

    def list_tasks(self, session_id: str, status: Optional[TaskStatus] = None) -> list[Task]:
        if status is None:
            rows = self.conn.execute(
                "SELECT * FROM tasks WHERE session_id = ? ORDER BY exec_order, id",
                (session_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT * FROM tasks
                WHERE session_id = ? AND status = ?
                ORDER BY exec_order, id
                """,
                (session_id, status.value),
            ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def update_task_status(
        self,
        session_id: str,
        task_id: str,
        new_status: TaskStatus,
        expected_status: Optional[TaskStatus] = None,
        **extra_fields,
    ) -> bool:
        set_parts = ["status = ?"]
        params: list[object] = [new_status.value]
        allowed_fields = {
            "worker_slot",
            "phase",
            "phase_num",
            "phase_total",
            "detail",
            "blocked_reason",
            "started_at",
            "completed_at",
            "plan_filename",
        }
        for key, value in extra_fields.items():
            if key not in allowed_fields:
                continue
            set_parts.append(f"{key} = ?")
            if key in {"started_at", "completed_at"} and isinstance(value, datetime):
                params.append(value.isoformat())
            else:
                params.append(value)

        where = "session_id = ? AND id = ?"
        params.extend([session_id, task_id])
        if expected_status is not None:
            where += " AND status = ?"
            params.append(expected_status.value)

        cursor = self.conn.execute(
            f"UPDATE tasks SET {', '.join(set_parts)} WHERE {where}",
            params,
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def create_worker_slots(self, session_id: str, num_workers: int) -> None:
        for slot in range(num_workers):
            self.conn.execute(
                """
                INSERT OR REPLACE INTO worker_slots
                (session_id, slot_number, status, current_task_id, pid)
                VALUES (?, ?, 'idle', NULL, NULL)
                """,
                (session_id, slot),
            )
        self.conn.commit()

    def get_worker_slots(self, session_id: str) -> list[WorkerSlot]:
        rows = self.conn.execute(
            """
            SELECT * FROM worker_slots
            WHERE session_id = ?
            ORDER BY slot_number
            """,
            (session_id,),
        ).fetchall()
        return [
            WorkerSlot(
                session_id=row["session_id"],
                slot_number=row["slot_number"],
                status=WorkerStatus(row["status"]),
                current_task_id=row["current_task_id"],
                pid=row["pid"],
            )
            for row in rows
        ]

    def update_worker_slot(
        self,
        session_id: str,
        slot_number: int,
        status: WorkerStatus,
        current_task_id: Optional[str] = None,
        pid: Optional[int] = None,
    ) -> None:
        self.conn.execute(
            """
            UPDATE worker_slots
            SET status = ?, current_task_id = ?, pid = ?
            WHERE session_id = ? AND slot_number = ?
            """,
            (status.value, current_task_id, pid, session_id, slot_number),
        )
        self.conn.commit()

    def add_event(self, event: Event) -> None:
        self.conn.execute(
            """
            INSERT INTO events (session_id, timestamp, event_type, task_id, worker_slot, message)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event.session_id,
                event.timestamp.isoformat(),
                event.event_type.value,
                event.task_id,
                event.worker_slot,
                event.message,
            ),
        )
        self.conn.commit()

    def list_events(self, session_id: str, limit: int = 100) -> list[Event]:
        rows = self.conn.execute(
            """
            SELECT * FROM events
            WHERE session_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
        return [
            Event(
                session_id=row["session_id"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
                event_type=EventType(row["event_type"]),
                task_id=row["task_id"],
                worker_slot=row["worker_slot"],
                message=row["message"],
            )
            for row in rows
        ]

    def pipeline_counts(self, session_id: str) -> dict[str, int]:
        rows = self.conn.execute(
            """
            SELECT status, COUNT(*) AS cnt
            FROM tasks
            WHERE session_id = ?
            GROUP BY status
            """,
            (session_id,),
        ).fetchall()
        counts = {status.value: 0 for status in TaskStatus}
        for row in rows:
            counts[row["status"]] = row["cnt"]
        return counts

    def reconcile_tasks_from_filesystem(self, session_id: str) -> None:
        dirs = config.session_subdirs(session_id)
        dir_status_map = {
            dirs["intake"]: TaskStatus.INTAKE,
            dirs["claimed"]: TaskStatus.PLANNING,
            dirs["staging"]: TaskStatus.STAGED,
            dirs["review"]: TaskStatus.REVIEW,
            dirs["ready"]: TaskStatus.READY,
            dirs["done"]: TaskStatus.DONE,
            dirs["blocked"]: TaskStatus.BLOCKED,
        }

        for directory, status in dir_status_map.items():
            if not directory.exists():
                continue
            for plan_file in directory.glob("*.plan.md"):
                task_id = self._extract_task_id_from_filename(plan_file.name)
                if task_id:
                    self.conn.execute(
                        "UPDATE tasks SET status = ?, worker_slot = NULL WHERE session_id = ? AND id = ?",
                        (status.value, session_id, task_id),
                    )

        workers_base = dirs["workers"]
        if workers_base.exists():
            for slot_dir in workers_base.iterdir():
                if not slot_dir.is_dir():
                    continue
                try:
                    slot_number = int(slot_dir.name)
                except ValueError:
                    continue
                for plan_file in slot_dir.glob("*.plan.md"):
                    task_id = self._extract_task_id_from_filename(plan_file.name)
                    if task_id:
                        self.conn.execute(
                            """
                            UPDATE tasks
                            SET status = ?, worker_slot = ?
                            WHERE session_id = ? AND id = ?
                            """,
                            (TaskStatus.ACTIVE.value, slot_number, session_id, task_id),
                        )

        self.conn.commit()
        logger.info("Reconciled task statuses from filesystem for session %s", session_id)

    @staticmethod
    def _extract_task_id_from_filename(filename: str) -> Optional[str]:
        base = filename.split("_", 1)[0] if "_" in filename else filename.split(".", 1)[0]
        normalized = base.replace("-", "")
        return normalized or None

    @staticmethod
    def _row_to_session(row: sqlite3.Row) -> Session:
        return Session(
            id=row["id"],
            name=row["name"],
            pack_name=row["pack_name"],
            config_json=row["config_json"],
            status=SessionStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            abort_reason=row["abort_reason"],
        )

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> Task:
        return Task(
            id=row["id"],
            session_id=row["session_id"],
            title=row["title"],
            status=TaskStatus(row["status"]),
            phase=row["phase"],
            phase_num=row["phase_num"],
            phase_total=row["phase_total"],
            detail=row["detail"],
            worker_slot=row["worker_slot"],
            depends_on=json.loads(row["depends_on"]) if row["depends_on"] else [],
            anti_affinity=json.loads(row["anti_affinity"]) if row["anti_affinity"] else [],
            exec_order=row["exec_order"],
            plan_filename=row["plan_filename"],
            blocked_reason=row["blocked_reason"],
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
        )
