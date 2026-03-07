from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response

from cognitive_switchyard.config import (
    GlobalConfig,
    SessionConfig,
    ensure_directories,
    session_dir,
    session_subdirs,
)
from cognitive_switchyard.html_template import get_html
from cognitive_switchyard.models import Session, SessionStatus, StatusSidecar, Task, TaskStatus
from cognitive_switchyard.orchestrator import Orchestrator
from cognitive_switchyard.pack_loader import (
    bootstrap_packs,
    check_scripts_executable,
    list_packs,
    load_pack,
    run_preflight,
)
from cognitive_switchyard.state import StateStore

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Track websocket clients and optional log subscriptions."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []
        self.log_subscriptions: dict[int, set[WebSocket]] = {}

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active_connections.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.active_connections:
            self.active_connections.remove(ws)
        for subscriptions in self.log_subscriptions.values():
            subscriptions.discard(ws)

    async def broadcast(self, message: dict[str, Any]) -> None:
        text = json.dumps(message)
        disconnected: list[WebSocket] = []
        for ws in self.active_connections:
            try:
                await ws.send_text(text)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            self.disconnect(ws)

    async def send_to_log_subscribers(self, slot: int, message: dict[str, Any]) -> None:
        text = json.dumps(message)
        for ws in list(self.log_subscriptions.get(slot, set())):
            try:
                await ws.send_text(text)
            except Exception:
                self.disconnect(ws)


ws_manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_directories()
    bootstrap_packs()
    store = StateStore()
    store.connect()
    app.state.sync_store = store
    app.state.orchestrators = {}
    _purge_expired_sessions()
    yield
    for orchestrator in app.state.orchestrators.values():
        orchestrator.stop()
    store.close()


app = FastAPI(title="Cognitive Switchyard", lifespan=lifespan)


def _store() -> StateStore:
    return app.state.sync_store


def _orchestrators() -> dict[str, Orchestrator]:
    return app.state.orchestrators


def _parse_session_config(session: Session) -> dict[str, Any]:
    try:
        return json.loads(session.config_json or "{}")
    except json.JSONDecodeError:
        return {}


def _session_paths(session_id: str) -> dict[str, str]:
    return {
        name: str(path)
        for name, path in session_subdirs(session_id).items()
        if name != "logs_workers"
    }


def _serialize_pack_config(name: str) -> dict[str, Any]:
    pack = load_pack(name)
    return {
        "name": pack.name,
        "description": pack.description,
        "version": pack.version,
        "phases": {
            "planning": {
                "enabled": pack.planning_enabled,
                "executor": pack.planning_executor,
                "model": pack.planning_model,
                "max_instances": pack.planning_max_instances,
            },
            "resolution": {
                "enabled": pack.resolution_enabled,
                "executor": pack.resolution_executor,
                "model": pack.resolution_model,
            },
            "execution": {
                "executor": pack.execution_executor,
                "model": pack.execution_model,
                "max_workers": pack.execution_max_workers,
            },
            "verification": {
                "enabled": pack.verification_enabled,
                "interval": pack.verification_interval,
            },
        },
        "auto_fix": {
            "enabled": pack.auto_fix_enabled,
            "max_attempts": pack.auto_fix_max_attempts,
            "mode": "script" if pack.auto_fix_script else ("agent" if pack.auto_fix_prompt else "disabled"),
        },
        "timeouts": {
            "task_idle": pack.task_idle_timeout,
            "task_max": pack.task_max_timeout,
            "session_max": pack.session_max_timeout,
        },
        "prerequisites": pack.prerequisites,
    }


def _serialize_session(session: Session) -> dict[str, Any]:
    return {
        "id": session.id,
        "name": session.name,
        "pack_name": session.pack_name,
        "status": session.status.value,
        "created_at": session.created_at.isoformat(),
        "started_at": session.started_at.isoformat() if session.started_at else None,
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        "abort_reason": session.abort_reason,
        "config": _parse_session_config(session),
    }


def _serialize_task(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "session_id": task.session_id,
        "title": task.title,
        "status": task.status.value,
        "phase": task.phase,
        "phase_num": task.phase_num,
        "phase_total": task.phase_total,
        "detail": task.detail,
        "worker_slot": task.worker_slot,
        "depends_on": task.depends_on,
        "anti_affinity": task.anti_affinity,
        "exec_order": task.exec_order,
        "plan_filename": task.plan_filename,
        "blocked_reason": task.blocked_reason,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


def _resolve_task_file(session_id: str, task: Task, suffix: str) -> Optional[Path]:
    candidates: list[Path] = []
    for directory in session_subdirs(session_id).values():
        if not directory.exists():
            continue
        if task.plan_filename and suffix == ".plan.md":
            candidate = directory / task.plan_filename
            if candidate.exists():
                return candidate
        candidates.extend(sorted(directory.glob(f"{task.id}*{suffix}")))
    return candidates[0] if candidates else None


def _task_log_path(session_id: str, task_id: str) -> Optional[Path]:
    base = session_dir(session_id)
    matches = sorted(base.glob(f"**/{task_id}*.log"))
    return matches[0] if matches else None


def _open_in_file_manager(path: Path, *, reveal: bool = False) -> None:
    if sys.platform == "darwin":
        command = ["open", "-R", str(path)] if reveal else ["open", str(path)]
    else:
        target = path.parent if reveal else path
        command = ["xdg-open", str(target)]
    subprocess.Popen(command)


def _purge_completed_session(session_id: str) -> None:
    _store().delete_session(session_id)
    shutil.rmtree(session_dir(session_id), ignore_errors=True)
    _orchestrators().pop(session_id, None)


def _purge_expired_sessions() -> int:
    retention_days = GlobalConfig.load().retention_days
    if retention_days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    purged = 0
    for session in list(_store().list_sessions()):
        if session.completed_at and session.completed_at <= cutoff:
            _purge_completed_session(session.id)
            purged += 1
    return purged


def _extract_title_from_plan(plan_path: Path) -> str:
    in_frontmatter = False
    for raw_line in plan_path.read_text().splitlines():
        line = raw_line.strip()
        if line == "---":
            in_frontmatter = not in_frontmatter
            continue
        if in_frontmatter:
            continue
        if line.startswith("# "):
            title = line[2:].strip()
            if title.lower().startswith("plan"):
                parts = title.split(":", 1)
                if len(parts) > 1:
                    return parts[1].strip()
            return title
    return plan_path.stem


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return get_html()


@app.get("/api/packs")
async def api_list_packs() -> list[dict[str, Any]]:
    return [_serialize_pack_config(pack.name) for pack in list_packs()]


@app.get("/api/packs/{name}")
async def api_get_pack(name: str) -> dict[str, Any]:
    try:
        return _serialize_pack_config(name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/packs/{name}/preflight")
async def api_preflight_pack(name: str) -> dict[str, Any]:
    try:
        load_pack(name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    executable_checks = [
        {
            "name": path,
            "passed": False,
            "detail": fix,
            "kind": "executable",
        }
        for path, fix in check_scripts_executable(name)
    ]
    pack_checks = [
        {
            "name": check_name,
            "passed": passed,
            "detail": detail,
            "kind": "prerequisite",
        }
        for check_name, passed, detail in run_preflight(name)
    ]
    return {
        "checks": executable_checks + pack_checks,
        "ok": all(check["passed"] for check in executable_checks + pack_checks),
    }


@app.post("/api/sessions")
async def api_create_session(payload: dict[str, Any]) -> dict[str, Any]:
    pack_name = payload.get("pack_name")
    if not pack_name:
        raise HTTPException(status_code=400, detail="pack_name is required")

    pack = load_pack(pack_name)
    session_id = payload.get("session_id") or str(uuid.uuid4())[:8]
    session_name = payload.get("name") or f"{pack_name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    config = SessionConfig(
        pack_name=pack_name,
        session_name=session_name,
        num_workers=int(payload.get("num_workers") or pack.execution_max_workers),
        num_planners=int(payload.get("num_planners") or 1),
        poll_interval=int(payload.get("poll_interval") or 5),
        verification_interval=int(payload.get("verification_interval") or pack.verification_interval),
        auto_fix_enabled=bool(payload.get("auto_fix_enabled", pack.auto_fix_enabled)),
        auto_fix_max_attempts=int(payload.get("auto_fix_max_attempts") or pack.auto_fix_max_attempts),
        task_idle_timeout=pack.task_idle_timeout,
        task_max_timeout=pack.task_max_timeout,
        session_max_timeout=pack.session_max_timeout,
        env_vars=payload.get("env_vars") or {},
    )

    session = Session(
        id=session_id,
        name=session_name,
        pack_name=pack_name,
        config_json=json.dumps(config.__dict__),
        status=SessionStatus.CREATED,
        created_at=datetime.now(timezone.utc),
    )
    _store().create_session(session)
    dirs = session_subdirs(session_id)
    for directory in dirs.values():
        directory.mkdir(parents=True, exist_ok=True)
    return {
        "session_id": session_id,
        "name": session_name,
        "session": _serialize_session(session),
        "paths": _session_paths(session_id),
    }


@app.get("/api/sessions")
async def api_list_sessions() -> list[dict[str, Any]]:
    return [
        {
            "session": _serialize_session(session),
            "pipeline": _store().pipeline_counts(session.id),
        }
        for session in _store().list_sessions()
    ]


@app.get("/api/sessions/{session_id}")
async def api_get_session(session_id: str) -> dict[str, Any]:
    session = _store().get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "session": _serialize_session(session),
        "pipeline": _store().pipeline_counts(session_id),
        "paths": _session_paths(session_id),
    }


@app.post("/api/sessions/{session_id}/start")
async def api_start_session(session_id: str) -> dict[str, Any]:
    session = _store().get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    if session_id not in _orchestrators():
        _orchestrators()[session_id] = Orchestrator(
            session_id,
            _store(),
            event_loop=asyncio.get_running_loop(),
            ws_broadcast=ws_manager.broadcast,
        )
        _orchestrators()[session_id].start_background()
    return {"started": True}


@app.post("/api/sessions/{session_id}/pause")
async def api_pause_session(session_id: str) -> dict[str, Any]:
    if not _store().update_session_status(session_id, SessionStatus.PAUSED):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"paused": True}


@app.post("/api/sessions/{session_id}/resume")
async def api_resume_session(session_id: str) -> dict[str, Any]:
    if not _store().update_session_status(session_id, SessionStatus.RUNNING):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"resumed": True}


@app.post("/api/sessions/{session_id}/abort")
async def api_abort_session(session_id: str) -> dict[str, Any]:
    orchestrator = _orchestrators().get(session_id)
    if orchestrator is not None:
        orchestrator.stop()
    if not _store().update_session_status(
        session_id,
        SessionStatus.ABORTED,
        abort_reason="Aborted via API",
        completed_at=datetime.now(timezone.utc),
    ):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"aborted": True}


@app.get("/api/sessions/{session_id}/tasks")
async def api_list_tasks(session_id: str) -> list[dict[str, Any]]:
    return [_serialize_task(task) for task in _store().list_tasks(session_id)]


@app.get("/api/sessions/{session_id}/tasks/{task_id}")
async def api_get_task(session_id: str, task_id: str) -> dict[str, Any]:
    task = _store().get_task(session_id, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    plan_path = _resolve_task_file(session_id, task, ".plan.md")
    status_path = _resolve_task_file(session_id, task, ".status")
    log_path = _task_log_path(session_id, task_id)
    return {
        **_serialize_task(task),
        "plan_path": str(plan_path) if plan_path else None,
        "plan_content": plan_path.read_text() if plan_path and plan_path.exists() else "",
        "status_path": str(status_path) if status_path else None,
        "status_sidecar": StatusSidecar.from_file(status_path).__dict__ if status_path else StatusSidecar().__dict__,
        "log_path": str(log_path) if log_path else None,
    }


@app.get("/api/sessions/{session_id}/tasks/{task_id}/log")
async def api_get_task_log(
    session_id: str,
    task_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(5000, ge=1),
) -> dict[str, Any]:
    log_path = _task_log_path(session_id, task_id)
    if log_path is None:
        return {"content": "", "path": None}
    content = log_path.read_text()
    return {"path": str(log_path), "content": content[offset : offset + limit]}


@app.get("/api/sessions/{session_id}/dag")
async def api_get_dag(session_id: str) -> dict[str, Any]:
    resolution_path = session_dir(session_id) / "resolution.json"
    if not resolution_path.exists():
        return {"tasks": [], "groups": [], "conflicts": [], "notes": ""}
    return json.loads(resolution_path.read_text())


@app.get("/api/sessions/{session_id}/dashboard")
async def api_get_dashboard(session_id: str) -> dict[str, Any]:
    session = _store().get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    tasks_by_id = {task.id: task for task in _store().list_tasks(session_id)}
    return {
        "session": _serialize_session(session),
        "pipeline": _store().pipeline_counts(session_id),
        "workers": [
            {
                "slot": slot.slot_number,
                "status": slot.status.value,
                "task_id": slot.current_task_id,
                "pid": slot.pid,
                "task_title": tasks_by_id[slot.current_task_id].title if slot.current_task_id in tasks_by_id else None,
                "phase": tasks_by_id[slot.current_task_id].phase if slot.current_task_id in tasks_by_id else None,
                "phase_num": tasks_by_id[slot.current_task_id].phase_num if slot.current_task_id in tasks_by_id else None,
                "phase_total": tasks_by_id[slot.current_task_id].phase_total if slot.current_task_id in tasks_by_id else None,
                "detail": tasks_by_id[slot.current_task_id].detail if slot.current_task_id in tasks_by_id else None,
                "elapsed": int(
                    (
                        datetime.now(timezone.utc) - tasks_by_id[slot.current_task_id].started_at
                    ).total_seconds()
                )
                if slot.current_task_id in tasks_by_id and tasks_by_id[slot.current_task_id].started_at
                else 0,
            }
            for slot in _store().get_worker_slots(session_id)
        ],
    }


@app.post("/api/sessions/{session_id}/tasks/{task_id}/retry")
async def api_retry_task(session_id: str, task_id: str) -> dict[str, Any]:
    task = _store().get_task(session_id, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != TaskStatus.BLOCKED:
        raise HTTPException(status_code=409, detail="Task is not blocked")

    dirs = session_subdirs(session_id)
    plan_file = next(iter(dirs["blocked"].glob(f"{task_id}*.plan.md")), None)
    if plan_file is None:
        raise HTTPException(status_code=404, detail="Blocked plan file not found")
    os_path = dirs["ready"] / plan_file.name
    plan_file.rename(os_path)
    for sidecar in dirs["blocked"].glob(f"{task_id}*.status"):
        sidecar.unlink()
    _store().update_task_status(session_id, task_id, TaskStatus.READY, blocked_reason="")
    return {"retried": True}


@app.get("/api/sessions/{session_id}/intake")
async def api_get_intake(session_id: str) -> list[dict[str, Any]]:
    intake_dir = session_subdirs(session_id)["intake"]
    session = _store().get_session(session_id)
    locked = session is not None and session.status != SessionStatus.CREATED
    files = []
    for path in sorted(intake_dir.glob("*")):
        if not path.is_file():
            continue
        stat = path.stat()
        files.append(
            {
                "name": path.name,
                "relative_path": str(path.relative_to(session_dir(session_id))),
                "size": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                "locked": locked,
            }
        )
    return files


@app.get("/api/sessions/{session_id}/open-intake")
async def api_open_intake(session_id: str) -> Response:
    intake_dir = session_subdirs(session_id)["intake"]
    _open_in_file_manager(intake_dir)
    return Response(status_code=204)


@app.get("/api/sessions/{session_id}/reveal-file")
async def api_reveal_file(session_id: str, path: str) -> Response:
    session_base = session_dir(session_id).resolve()
    target = (session_base / path).resolve()
    if session_base not in [target, *target.parents]:
        raise HTTPException(status_code=400, detail="Path must be inside the session directory")
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    _open_in_file_manager(target, reveal=True)
    return Response(status_code=204)


@app.delete("/api/sessions/{session_id}")
async def api_delete_session(session_id: str) -> dict[str, Any]:
    session = _store().get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status in {SessionStatus.RUNNING, SessionStatus.PLANNING, SessionStatus.RESOLVING, SessionStatus.VERIFYING}:
        raise HTTPException(status_code=409, detail="Cannot delete an active session")
    _purge_completed_session(session_id)
    return {"deleted": True}


@app.delete("/api/sessions")
async def api_purge_sessions() -> dict[str, Any]:
    purged = 0
    for session in list(_store().list_sessions()):
        if session.status in {SessionStatus.COMPLETED, SessionStatus.ABORTED}:
            _purge_completed_session(session.id)
            purged += 1
    return {"purged": purged}


@app.get("/api/settings")
async def api_get_settings() -> dict[str, Any]:
    return GlobalConfig.load().__dict__


@app.put("/api/settings")
async def api_put_settings(payload: dict[str, Any]) -> dict[str, Any]:
    current = GlobalConfig.load()
    current.retention_days = int(payload.get("retention_days", current.retention_days))
    current.default_planners = int(payload.get("default_planners", current.default_planners))
    current.default_workers = int(payload.get("default_workers", current.default_workers))
    current.default_pack = str(payload.get("default_pack", current.default_pack))
    current.save()
    return current.__dict__


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws_manager.connect(ws)
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            if msg.get("type") == "subscribe_logs":
                slot = msg.get("worker_slot")
                if slot is not None:
                    ws_manager.log_subscriptions.setdefault(int(slot), set()).add(ws)
            elif msg.get("type") == "unsubscribe_logs":
                slot = msg.get("worker_slot")
                if slot is not None:
                    ws_manager.log_subscriptions.get(int(slot), set()).discard(ws)
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)
