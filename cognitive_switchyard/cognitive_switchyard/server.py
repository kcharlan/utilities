from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Query, Response, WebSocket, WebSocketDisconnect

from .config import GlobalConfig, RuntimePaths, load_global_config, write_global_config
from .models import (
    BackendRuntimeEvent,
    HookInvocationResult,
    PackManifest,
    PackPreflightResult,
    PersistedTask,
    PrerequisiteReport,
    ScriptPermissionReport,
    SessionRecord,
    WorkerCardRuntimeState,
    apply_runtime_event_to_worker_card_state,
)
from .orchestrator import run_session_preflight, start_session
from .pack_loader import list_runtime_pack_names, load_pack_manifest
from .parsers import ArtifactParseError, parse_progress_line
from .state import StateStore, initialize_state_store


CommandRunner = Callable[[list[str]], None]


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []
        self.log_subscriptions: dict[int, set[WebSocket]] = {}
        self._lock = asyncio.Lock()
        self._event_loop: asyncio.AbstractEventLoop | None = None

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._event_loop = asyncio.get_running_loop()
        async with self._lock:
            self.active_connections.append(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
            for subscribers in self.log_subscriptions.values():
                subscribers.discard(websocket)

    async def subscribe_logs(self, websocket: WebSocket, worker_slot: int) -> None:
        async with self._lock:
            self.log_subscriptions.setdefault(worker_slot, set()).add(websocket)

    async def unsubscribe_logs(self, websocket: WebSocket, worker_slot: int) -> None:
        async with self._lock:
            self.log_subscriptions.setdefault(worker_slot, set()).discard(websocket)

    async def broadcast_state(self, state: dict[str, Any]) -> None:
        await self._broadcast({"type": "state_update", "data": state})

    async def send_log_line(self, slot: int, payload: dict[str, Any]) -> None:
        async with self._lock:
            subscribers = tuple(self.log_subscriptions.get(slot, set()))
        await self._send_many(subscribers, {"type": "log_line", "data": payload})

    async def broadcast_task_status_change(self, payload: dict[str, Any]) -> None:
        await self._broadcast({"type": "task_status_change", "data": payload})

    async def broadcast_progress_detail(self, payload: dict[str, Any]) -> None:
        await self._broadcast({"type": "progress_detail", "data": payload})

    async def broadcast_alert(self, payload: dict[str, Any]) -> None:
        await self._broadcast({"type": "alert", "data": payload})

    async def _broadcast(self, payload: dict[str, Any]) -> None:
        async with self._lock:
            connections = tuple(self.active_connections)
        await self._send_many(connections, payload)

    async def _send_many(self, connections: tuple[WebSocket, ...], payload: dict[str, Any]) -> None:
        stale: list[WebSocket] = []
        for connection in connections:
            try:
                await connection.send_json(payload)
            except Exception:
                stale.append(connection)
        for connection in stale:
            await self.disconnect(connection)

    @property
    def event_loop(self) -> asyncio.AbstractEventLoop | None:
        return self._event_loop


class SessionController:
    def __init__(
        self,
        *,
        store: StateStore,
        runtime_paths: RuntimePaths,
        connection_manager: ConnectionManager,
    ) -> None:
        self.store = store
        self.runtime_paths = runtime_paths
        self.connection_manager = connection_manager
        self._threads: dict[str, threading.Thread] = {}
        self._worker_card_state: dict[str, dict[int, WorkerCardRuntimeState]] = {}
        self._lock = threading.Lock()

    def create_session(self, *, session_id: str, name: str, pack: str) -> SessionRecord:
        return self.store.create_session(
            session_id=session_id,
            name=name,
            pack=pack,
            created_at=_timestamp(),
        )

    def start(self, session_id: str) -> None:
        self._launch_background_session(session_id)

    def preflight(self, session_id: str) -> PackPreflightResult:
        session = self.store.get_session(session_id)
        pack_manifest = load_pack_manifest(self.runtime_paths.packs / session.pack)
        return run_session_preflight(
            store=self.store,
            session_id=session_id,
            pack_manifest=pack_manifest,
        )

    def pause(self, session_id: str) -> None:
        self.store.update_session_status(session_id, status="paused")
        self._publish_snapshot(session_id)

    def resume(self, session_id: str) -> None:
        self.store.update_session_status(session_id, status="running")
        self._publish_snapshot(session_id)
        self._launch_background_session(session_id)

    def abort(self, session_id: str) -> None:
        self.store.update_session_status(
            session_id,
            status="aborted",
            completed_at=_timestamp(),
        )
        self._publish_snapshot(session_id)

    def retry_task(self, session_id: str, task_id: str) -> PersistedTask:
        task = self.store.get_task(session_id, task_id)
        if task.status == "ready":
            return task
        retried = self.store.project_task(
            session_id,
            task_id,
            status="ready",
        )
        self._publish_snapshot(session_id)
        return retried

    def _launch_background_session(self, session_id: str) -> None:
        with self._lock:
            thread = self._threads.get(session_id)
            if thread is not None and thread.is_alive():
                return
            thread = threading.Thread(
                target=self._run_session,
                args=(session_id,),
                name=f"switchyard-session-{session_id}",
                daemon=True,
            )
            self._threads[session_id] = thread
            thread.start()

    def _run_session(self, session_id: str) -> None:
        session = self.store.get_session(session_id)
        pack_manifest = load_pack_manifest(self.runtime_paths.packs / session.pack)
        start_session(
            store=self.store,
            session_id=session_id,
            pack_manifest=pack_manifest,
            env=None,
            poll_interval=0.05,
            runtime_event_sink=self._publish_runtime_event,
        )
        self._publish_snapshot(session_id)

    def _publish_snapshot(self, session_id: str) -> None:
        try:
            state = build_dashboard_payload(
                self.store,
                session_id,
                runtime_paths=self.runtime_paths,
                worker_card_state=self.get_worker_card_state(session_id),
            )
        except KeyError:
            return
        _run_async(
            self.connection_manager.broadcast_state(state),
            loop=self.connection_manager.event_loop,
        )

    def _publish_runtime_event(self, event: BackendRuntimeEvent) -> None:
        self._update_worker_card_state(event)
        if event.message_type == "state_update":
            self._publish_snapshot(event.session_id)
            return
        if event.message_type == "task_status_change":
            _run_async(
                self.connection_manager.broadcast_task_status_change(event.data),
                loop=self.connection_manager.event_loop,
            )
            return
        if event.message_type == "progress_detail":
            _run_async(
                self.connection_manager.broadcast_progress_detail(event.data),
                loop=self.connection_manager.event_loop,
            )
            return
        if event.message_type == "alert":
            _run_async(
                self.connection_manager.broadcast_alert(event.data),
                loop=self.connection_manager.event_loop,
            )
            return
        if event.message_type == "log_line":
            worker_slot = event.data.get("worker_slot")
            if isinstance(worker_slot, int):
                _run_async(
                    self.connection_manager.send_log_line(worker_slot, event.data),
                    loop=self.connection_manager.event_loop,
                )

    def get_worker_card_state(self, session_id: str) -> dict[int, WorkerCardRuntimeState]:
        with self._lock:
            return dict(self._worker_card_state.get(session_id, {}))

    def _update_worker_card_state(self, event: BackendRuntimeEvent) -> None:
        with self._lock:
            session_cache = self._worker_card_state.setdefault(event.session_id, {})
            apply_runtime_event_to_worker_card_state(
                session_cache,
                self._phase_enriched_log_event(event),
            )

    def _phase_enriched_log_event(self, event: BackendRuntimeEvent) -> BackendRuntimeEvent:
        if event.message_type != "log_line":
            return event
        line = event.data.get("line")
        task_id = event.data.get("task_id")
        if not isinstance(line, str) or not isinstance(task_id, str):
            return event
        session = self.store.get_session(event.session_id)
        pack_manifest = load_pack_manifest(self.runtime_paths.packs / session.pack)
        try:
            progress = parse_progress_line(line, progress_format=pack_manifest.status.progress_format)
        except ArtifactParseError:
            return event
        if progress.kind != "phase" or progress.task_id != task_id:
            return event
        payload = dict(event.data)
        payload["phase"] = progress.phase_name
        payload["phase_num"] = progress.phase_index
        payload["phase_total"] = progress.phase_total
        return BackendRuntimeEvent(
            message_type=event.message_type,
            session_id=event.session_id,
            data=payload,
        )


def create_app(
    *,
    store: StateStore,
    runtime_paths: RuntimePaths,
    controller: SessionController | Any | None = None,
    command_runner: CommandRunner | None = None,
) -> FastAPI:
    app = FastAPI(title="Cognitive Switchyard Backend")
    connection_manager = ConnectionManager()
    session_controller = controller or SessionController(
        store=store,
        runtime_paths=runtime_paths,
        connection_manager=connection_manager,
    )
    app.state.store = store
    app.state.runtime_paths = runtime_paths
    app.state.connection_manager = connection_manager
    app.state.controller = session_controller
    app.state.command_runner = command_runner or _default_command_runner

    @app.get("/")
    def read_root() -> dict[str, str]:
        return {"status": "backend_only"}

    @app.get("/api/packs")
    def get_packs() -> dict[str, list[dict[str, Any]]]:
        packs = []
        for pack_name in list_runtime_pack_names(runtime_paths.packs):
            manifest = load_pack_manifest(runtime_paths.packs / pack_name)
            packs.append(_serialize_pack_summary(manifest))
        return {"packs": packs}

    @app.get("/api/packs/{name}")
    def get_pack_detail(name: str) -> dict[str, Any]:
        manifest = _load_runtime_pack(runtime_paths, name)
        return _serialize_pack_detail(manifest)

    @app.post("/api/sessions", status_code=201)
    def create_session(payload: dict[str, str]) -> dict[str, Any]:
        session_id = payload["id"]
        name = payload.get("name", session_id)
        pack = payload.get("pack") or load_global_config(runtime_paths.config).default_pack
        if hasattr(session_controller, "create_session"):
            created = session_controller.create_session(session_id=session_id, name=name, pack=pack)
        else:
            created = store.create_session(
                session_id=session_id,
                name=name,
                pack=pack,
                created_at=_timestamp(),
            )
        return {"session": _serialize_session(created)}

    @app.get("/api/sessions")
    def list_sessions() -> dict[str, list[dict[str, Any]]]:
        return {"sessions": [_serialize_session(session) for session in store.list_sessions()]}

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str) -> dict[str, Any]:
        return {"session": _serialize_session(store.get_session(session_id))}

    @app.post("/api/sessions/{session_id}/start", status_code=202)
    def start_session_route(session_id: str) -> dict[str, str]:
        _ensure_session_exists(store, session_id)
        session_controller.start(session_id)
        return {"status": "accepted"}

    @app.post("/api/sessions/{session_id}/pause", status_code=202)
    def pause_session_route(session_id: str) -> dict[str, str]:
        _ensure_session_exists(store, session_id)
        session_controller.pause(session_id)
        return {"status": "accepted"}

    @app.post("/api/sessions/{session_id}/resume", status_code=202)
    def resume_session_route(session_id: str) -> dict[str, str]:
        _ensure_session_exists(store, session_id)
        session_controller.resume(session_id)
        return {"status": "accepted"}

    @app.post("/api/sessions/{session_id}/abort", status_code=202)
    def abort_session_route(session_id: str) -> dict[str, str]:
        _ensure_session_exists(store, session_id)
        session_controller.abort(session_id)
        return {"status": "accepted"}

    @app.get("/api/sessions/{session_id}/tasks")
    def get_tasks(session_id: str) -> dict[str, list[dict[str, Any]]]:
        _ensure_session_exists(store, session_id)
        tasks = [_serialize_task(store, session_id, task) for task in _list_session_tasks(store, session_id)]
        return {"tasks": tasks}

    @app.get("/api/sessions/{session_id}/tasks/{task_id}")
    def get_task_detail(session_id: str, task_id: str) -> dict[str, Any]:
        return {"task": _serialize_task(store, session_id, store.get_task(session_id, task_id))}

    @app.get("/api/sessions/{session_id}/tasks/{task_id}/log")
    def get_task_log(
        session_id: str,
        task_id: str,
        offset: int = Query(0, ge=0),
        limit: int = Query(200, ge=1),
    ) -> dict[str, Any]:
        task = store.get_task(session_id, task_id)
        log_path = _task_log_path(runtime_paths, task)
        if log_path is None or not log_path.is_file():
            return {"path": None, "offset": offset, "content": ""}
        lines = log_path.read_text(encoding="utf-8").splitlines()
        selected = lines[offset : offset + limit]
        return {
            "path": str(log_path),
            "offset": offset,
            "limit": limit,
            "content": "\n".join(selected) + ("\n" if selected else ""),
        }

    @app.get("/api/sessions/{session_id}/dag")
    def get_dag(session_id: str) -> dict[str, Any]:
        _ensure_session_exists(store, session_id)
        session_paths = runtime_paths.session_paths(session_id)
        if session_paths.resolution.is_file():
            return json.loads(session_paths.resolution.read_text(encoding="utf-8"))
        return {
            "resolved_at": None,
            "tasks": [
                {
                    "task_id": task.task_id,
                    "depends_on": list(task.depends_on),
                    "anti_affinity": list(task.anti_affinity),
                    "exec_order": task.exec_order,
                }
                for task in _list_session_tasks(store, session_id)
            ],
            "groups": [],
            "conflicts": [],
            "notes": None,
        }

    @app.get("/api/sessions/{session_id}/dashboard")
    def get_dashboard(session_id: str) -> dict[str, Any]:
        _ensure_session_exists(store, session_id)
        worker_card_state = {}
        if hasattr(session_controller, "get_worker_card_state"):
            worker_card_state = session_controller.get_worker_card_state(session_id)
        return build_dashboard_payload(
            store,
            session_id,
            runtime_paths=runtime_paths,
            worker_card_state=worker_card_state,
        )

    @app.post("/api/sessions/{session_id}/preflight")
    def run_preflight(session_id: str) -> dict[str, Any]:
        _ensure_session_exists(store, session_id)
        if hasattr(session_controller, "preflight"):
            result = session_controller.preflight(session_id)
        else:
            session = store.get_session(session_id)
            result = run_session_preflight(
                store=store,
                session_id=session_id,
                pack_manifest=load_pack_manifest(runtime_paths.packs / session.pack),
            )
        return _serialize_preflight_result(result)

    @app.post("/api/sessions/{session_id}/tasks/{task_id}/retry", status_code=202)
    def retry_task_route(session_id: str, task_id: str) -> dict[str, str]:
        store.get_task(session_id, task_id)
        session_controller.retry_task(session_id, task_id)
        return {"status": "accepted"}

    @app.get("/api/sessions/{session_id}/intake")
    def get_intake(session_id: str) -> dict[str, list[dict[str, Any]]]:
        _ensure_session_exists(store, session_id)
        session_paths = runtime_paths.session_paths(session_id)
        files = []
        for path in sorted(session_paths.intake.rglob("*")):
            files.append(
                {
                    "path": str(path.relative_to(session_paths.root)),
                    "is_dir": path.is_dir(),
                }
            )
        return {"files": files}

    @app.get("/api/sessions/{session_id}/open-intake", status_code=204)
    def open_intake(session_id: str) -> Response:
        _ensure_session_exists(store, session_id)
        command = _open_command(runtime_paths.session_paths(session_id).intake)
        app.state.command_runner(command)
        return Response(status_code=204)

    @app.get("/api/sessions/{session_id}/reveal-file", status_code=204)
    def reveal_file(session_id: str, path: str) -> Response:
        _ensure_session_exists(store, session_id)
        session_root = runtime_paths.session(session_id)
        target = _resolve_relative_path(session_root, path)
        command = _reveal_command(target)
        app.state.command_runner(command)
        return Response(status_code=204)

    @app.delete("/api/sessions/{session_id}")
    def purge_session(session_id: str) -> dict[str, int]:
        session = store.get_session(session_id)
        if session.status not in {"completed", "aborted"}:
            raise HTTPException(status_code=409, detail="Session is still active.")
        store.delete_session(session_id)
        return {"deleted": 1}

    @app.delete("/api/sessions")
    def purge_completed_sessions() -> dict[str, int]:
        deleted = 0
        for session in store.list_sessions():
            if session.status in {"completed", "aborted"}:
                store.delete_session(session.id)
                deleted += 1
        return {"deleted": deleted}

    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        config = load_global_config(runtime_paths.config)
        return {"settings": _serialize_settings(config)}

    @app.put("/api/settings")
    def update_settings(payload: dict[str, Any]) -> dict[str, Any]:
        config = GlobalConfig(
            retention_days=int(payload.get("retention_days", 30)),
            default_planners=int(payload.get("default_planners", 3)),
            default_workers=int(payload.get("default_workers", 3)),
            default_pack=str(payload.get("default_pack", "claude-code")),
        )
        write_global_config(runtime_paths.config, config)
        return {"settings": _serialize_settings(config)}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await connection_manager.connect(websocket)
        try:
            while True:
                payload = await websocket.receive_json()
                message_type = payload.get("type")
                worker_slot = payload.get("worker_slot")
                if message_type == "subscribe_logs" and isinstance(worker_slot, int):
                    await connection_manager.subscribe_logs(websocket, worker_slot)
                elif message_type == "unsubscribe_logs" and isinstance(worker_slot, int):
                    await connection_manager.unsubscribe_logs(websocket, worker_slot)
        except WebSocketDisconnect:
            await connection_manager.disconnect(websocket)

    return app


def serve_backend(
    *,
    runtime_paths: RuntimePaths,
    builtin_packs_root: Path,
    host: str,
    port: int,
) -> int:
    del builtin_packs_root
    resolved_port = find_free_port(port)
    store = initialize_state_store(runtime_paths)
    app = create_app(store=store, runtime_paths=runtime_paths)
    import uvicorn

    uvicorn.run(app, host=host, port=resolved_port)
    return resolved_port


def find_free_port(start_port: int, max_attempts: int = 20) -> int:
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
            try:
                candidate.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(
        f"No free port found in range {start_port}-{start_port + max_attempts - 1}"
    )


def build_dashboard_payload(
    store: StateStore,
    session_id: str,
    *,
    runtime_paths: RuntimePaths | None = None,
    worker_card_state: dict[int, WorkerCardRuntimeState] | None = None,
) -> dict[str, Any]:
    session = store.get_session(session_id)
    session_paths = store.runtime_paths.session_paths(session_id)
    resolved_runtime_paths = runtime_paths or store.runtime_paths
    pack_manifest = load_pack_manifest(resolved_runtime_paths.packs / session.pack)
    pipeline = {
        "intake": _count_plans(session_paths.intake),
        "planning": _count_plans(session_paths.claimed),
        "staged": _count_plans(session_paths.staging),
        "review": _count_plans(session_paths.review),
        "ready": len(store.list_ready_tasks(session_id)),
        "active": len(store.list_active_tasks(session_id)),
        "done": len(store.list_done_tasks(session_id)),
        "blocked": len(store.list_blocked_tasks(session_id)),
    }
    active_tasks_by_slot = {
        task.worker_slot: task
        for task in store.list_active_tasks(session_id)
        if task.worker_slot is not None
    }
    slot_rows = {slot.slot_number: slot for slot in store.list_worker_slots(session_id)}
    runtime_state_by_slot = worker_card_state or {}
    workers = []
    for slot_number in range(pack_manifest.phases.execution.max_workers):
        active_task = active_tasks_by_slot.get(slot_number)
        slot = slot_rows.get(slot_number)
        worker_payload: dict[str, Any] = {
            "slot": slot_number,
            "status": "active" if active_task is not None else (slot.status if slot is not None else "idle"),
        }
        if active_task is not None:
            task = active_task
            worker_payload["task_id"] = task.task_id
            worker_payload["task_title"] = task.title
            worker_payload["elapsed"] = int(_elapsed_seconds(task.started_at))
            runtime_worker = runtime_state_by_slot.get(slot_number)
            if runtime_worker is not None and runtime_worker.task_id == task.task_id:
                if runtime_worker.phase_name is not None:
                    worker_payload["phase"] = runtime_worker.phase_name
                if runtime_worker.phase_index is not None:
                    worker_payload["phase_num"] = runtime_worker.phase_index
                if runtime_worker.phase_total is not None:
                    worker_payload["phase_total"] = runtime_worker.phase_total
                if runtime_worker.detail_message is not None:
                    worker_payload["detail"] = runtime_worker.detail_message
        workers.append(worker_payload)
    return {
        "session": {
            "id": session.id,
            "status": session.status,
            "pack": session.pack,
            "started_at": session.started_at,
            "elapsed": int(_elapsed_seconds(session.started_at)),
        },
        "pipeline": pipeline,
        "workers": workers,
    }


def _serialize_pack_summary(manifest: PackManifest) -> dict[str, Any]:
    return {
        "name": manifest.name,
        "description": manifest.description,
        "version": manifest.version,
        "max_workers": manifest.phases.execution.max_workers,
        "planning_enabled": manifest.phases.planning.enabled,
        "verification_enabled": manifest.verification.enabled,
    }


def _serialize_pack_detail(manifest: PackManifest) -> dict[str, Any]:
    return {
        "name": manifest.name,
        "description": manifest.description,
        "version": manifest.version,
        "root": str(manifest.root),
        "phases": {
            "planning": {
                "enabled": manifest.phases.planning.enabled,
                "executor": manifest.phases.planning.executor,
                "model": manifest.phases.planning.model,
                "prompt": (
                    str(manifest.phases.planning.prompt)
                    if manifest.phases.planning.prompt is not None
                    else None
                ),
                "max_instances": manifest.phases.planning.max_instances,
            },
            "resolution": {
                "enabled": manifest.phases.resolution.enabled,
                "executor": manifest.phases.resolution.executor,
                "model": manifest.phases.resolution.model,
                "prompt": (
                    str(manifest.phases.resolution.prompt)
                    if manifest.phases.resolution.prompt is not None
                    else None
                ),
                "script": (
                    str(manifest.phases.resolution.script)
                    if manifest.phases.resolution.script is not None
                    else None
                ),
            },
            "execution": {
                "enabled": manifest.phases.execution.enabled,
                "executor": manifest.phases.execution.executor,
                "command": (
                    str(manifest.phases.execution.command)
                    if manifest.phases.execution.command is not None
                    else None
                ),
                "max_workers": manifest.phases.execution.max_workers,
            },
        },
        "timeouts": {
            "task_idle": manifest.timeouts.task_idle,
            "task_max": manifest.timeouts.task_max,
            "session_max": manifest.timeouts.session_max,
        },
    }


def _serialize_preflight_result(result: PackPreflightResult) -> dict[str, Any]:
    return {
        "ok": result.ok,
        "permission_report": _serialize_permission_report(result.permission_report),
        "prerequisite_results": _serialize_prerequisite_report(result.prerequisite_results),
        "preflight_result": (
            None if result.preflight_result is None else _serialize_hook_result(result.preflight_result)
        ),
    }


def _serialize_permission_report(report: ScriptPermissionReport) -> dict[str, Any]:
    return {
        "ok": report.ok,
        "issues": [
            {
                "relative_path": issue.relative_path,
                "fix_command": issue.fix_command,
            }
            for issue in report.issues
        ],
    }


def _serialize_prerequisite_report(report: PrerequisiteReport) -> dict[str, Any]:
    return {
        "ok": report.ok,
        "results": [
            {
                "name": result.name,
                "check": result.check,
                "ok": result.ok,
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
            for result in report.results
        ],
    }


def _serialize_hook_result(result: HookInvocationResult) -> dict[str, Any]:
    return {
        "hook_name": result.hook_name,
        "script_path": str(result.script_path),
        "args": list(result.args),
        "cwd": str(result.cwd),
        "ok": result.ok,
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _serialize_session(session: SessionRecord) -> dict[str, Any]:
    return {
        "id": session.id,
        "name": session.name,
        "pack": session.pack,
        "status": session.status,
        "created_at": session.created_at,
        "started_at": session.started_at,
        "completed_at": session.completed_at,
        "runtime_state": {
            "completed_since_verification": session.runtime_state.completed_since_verification,
            "verification_pending": session.runtime_state.verification_pending,
            "verification_reason": session.runtime_state.verification_reason,
            "auto_fix_context": session.runtime_state.auto_fix_context,
            "auto_fix_task_id": session.runtime_state.auto_fix_task_id,
            "auto_fix_attempt": session.runtime_state.auto_fix_attempt,
            "last_fix_summary": session.runtime_state.last_fix_summary,
        },
    }


def _serialize_task(store: StateStore, session_id: str, task: PersistedTask) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "title": task.title,
        "status": task.status,
        "depends_on": list(task.depends_on),
        "anti_affinity": list(task.anti_affinity),
        "exec_order": task.exec_order,
        "full_test_after": task.full_test_after,
        "worker_slot": task.worker_slot,
        "plan_path": str(task.plan_path),
        "log_path": (
            str(log_path)
            if (log_path := _task_log_path(store.runtime_paths, task)) is not None
            else None
        ),
        "created_at": task.created_at,
        "started_at": task.started_at,
        "completed_at": task.completed_at,
    }


def _serialize_settings(config: GlobalConfig) -> dict[str, Any]:
    return {
        "retention_days": config.retention_days,
        "default_planners": config.default_planners,
        "default_workers": config.default_workers,
        "default_pack": config.default_pack,
    }


def _list_session_tasks(store: StateStore, session_id: str) -> tuple[PersistedTask, ...]:
    return (
        *store.list_active_tasks(session_id),
        *store.list_ready_tasks(session_id),
        *store.list_done_tasks(session_id),
        *store.list_blocked_tasks(session_id),
    )


def _task_log_path(runtime_paths: RuntimePaths, task: PersistedTask) -> Path | None:
    if task.worker_slot is None:
        return None
    return runtime_paths.session_paths(task.session_id).worker_log(task.worker_slot)


def _load_runtime_pack(runtime_paths: RuntimePaths, name: str) -> PackManifest:
    pack_path = runtime_paths.packs / name
    if not pack_path.is_dir():
        raise HTTPException(status_code=404, detail="Unknown pack.")
    return load_pack_manifest(pack_path)


def _ensure_session_exists(store: StateStore, session_id: str) -> None:
    try:
        store.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown session.") from exc


def _resolve_relative_path(session_root: Path, relative_path: str) -> Path:
    candidate = (session_root / relative_path).resolve()
    try:
        candidate.relative_to(session_root.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Path escapes session root.") from exc
    return candidate


def _open_command(target: Path) -> list[str]:
    if sys.platform == "darwin":
        return ["open", str(target)]
    return ["xdg-open", str(target)]


def _reveal_command(target: Path) -> list[str]:
    if sys.platform == "darwin":
        return ["open", "-R", str(target)]
    return ["xdg-open", str(target.parent)]


def _default_command_runner(command: list[str]) -> None:
    subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _count_plans(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    return len(tuple(directory.glob("*.plan.md")))


def _timestamp() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _elapsed_seconds(timestamp: str | None) -> int:
    if not timestamp:
        return 0
    from datetime import UTC, datetime

    started_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return max(0, int((datetime.now(UTC) - started_at).total_seconds()))


def _run_async(awaitable, *, loop: asyncio.AbstractEventLoop | None = None) -> None:
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        if loop is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(awaitable, loop)
            return
        asyncio.run(awaitable)
        return
    running_loop.create_task(awaitable)
