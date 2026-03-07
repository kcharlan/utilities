from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from cognitive_switchyard.config import (
    SessionConfig,
    ensure_directories,
    find_free_port,
    session_dir,
    session_subdirs,
)
from cognitive_switchyard.models import Session, SessionStatus, Task, TaskStatus
from cognitive_switchyard.orchestrator import Orchestrator
from cognitive_switchyard.pack_loader import (
    bootstrap_packs,
    check_scripts_executable,
    list_packs,
    load_pack,
    reset_pack,
    run_preflight,
)
from cognitive_switchyard.resolution import parse_plan_frontmatter
from cognitive_switchyard.scheduler import load_resolution
from cognitive_switchyard.state import StateStore


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="cognitive_switchyard",
        description="Cognitive Switchyard -- Task Orchestration Engine",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    subparsers = parser.add_subparsers(dest="command")

    start_parser = subparsers.add_parser("start", help="Start a new orchestration session")
    start_parser.add_argument("--pack", required=True, help="Pack name")
    start_parser.add_argument("--name", help="Session name (auto-generated if omitted)")
    start_parser.add_argument("--workers", type=int, help="Number of worker slots")
    start_parser.add_argument("--poll", type=int, default=5, help="Poll interval (seconds)")
    start_parser.add_argument("--intake", help="Path to intake items or pre-staged plan files")

    subparsers.add_parser("list-packs", help="List available packs")
    reset_parser = subparsers.add_parser("reset-pack", help="Reset a pack to factory default")
    reset_parser.add_argument("name", help="Pack name")
    subparsers.add_parser("reset-all-packs", help="Reset all packs to factory defaults")
    subparsers.add_parser("history", help="List past sessions")
    serve_parser = subparsers.add_parser("serve", help="Start the web UI server")
    serve_parser.add_argument("--port", type=int, default=8100, help="Preferred port")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    ensure_directories()
    bootstrap_packs()

    if args.command == "list-packs":
        _cmd_list_packs()
    elif args.command == "reset-pack":
        _cmd_reset_pack(args.name)
    elif args.command == "reset-all-packs":
        _cmd_reset_all_packs()
    elif args.command == "history":
        _cmd_history()
    elif args.command == "serve":
        _cmd_serve(args)
    elif args.command == "start":
        _cmd_start(args)
    else:
        parser.print_help()


def _cmd_list_packs() -> None:
    packs = list_packs()
    if not packs:
        print("No packs installed.")
        return
    for pack in packs:
        print(f"  {pack.name:20s} {pack.description}")


def _cmd_reset_pack(name: str) -> None:
    if not reset_pack(name):
        print(f"Error: no built-in pack named '{name}'.", file=sys.stderr)
        raise SystemExit(1)
    print(f"Pack '{name}' reset to factory default.")


def _cmd_reset_all_packs() -> None:
    import cognitive_switchyard.config as config

    if not config.BUILTIN_PACKS_DIR.exists():
        print("No built-in packs directory found.")
        return

    count = 0
    for pack_path in sorted(config.BUILTIN_PACKS_DIR.iterdir()):
        if pack_path.is_dir() and (pack_path / "pack.yaml").exists():
            reset_pack(pack_path.name)
            count += 1
    print(f"Reset {count} pack(s) to factory defaults.")


def _cmd_history() -> None:
    store = StateStore()
    store.connect()
    try:
        sessions = store.list_sessions()
    finally:
        store.close()

    if not sessions:
        print("No sessions.")
        return

    for session in sessions:
        elapsed = ""
        if session.started_at and session.completed_at:
            elapsed = f" ({int((session.completed_at - session.started_at).total_seconds())}s)"
        print(
            f"  {session.id[:8]}  {session.name:30s} "
            f"{session.status.value:12s} {session.pack_name}{elapsed}"
        )


def _cmd_start(args: argparse.Namespace) -> None:
    try:
        pack = load_pack(args.pack)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)

    failures = check_scripts_executable(args.pack)
    if failures:
        print(f"ERROR: Pack '{args.pack}' has non-executable scripts:\n")
        for path, fix in failures:
            print(f"  {path}  -- Run: {fix}")
        print("\nFix the permissions above and re-run.")
        raise SystemExit(1)

    preflight_results = run_preflight(args.pack)
    all_passed = True
    for name, passed, detail in preflight_results:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        if not passed and detail:
            print(f"         {detail}")
            all_passed = False
    if not all_passed:
        print("\nPreflight checks failed. Fix the issues above and re-run.")
        raise SystemExit(1)

    session_id = str(uuid.uuid4())[:8]
    session_name = args.name or f"{args.pack}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    num_workers = args.workers or pack.execution_max_workers
    config = SessionConfig(
        pack_name=args.pack,
        session_name=session_name,
        num_workers=num_workers,
        poll_interval=args.poll,
        verification_interval=pack.verification_interval,
        task_idle_timeout=pack.task_idle_timeout,
        task_max_timeout=pack.task_max_timeout,
        session_max_timeout=pack.session_max_timeout,
    )

    store = StateStore()
    store.connect()
    try:
        session = Session(
            id=session_id,
            name=session_name,
            pack_name=args.pack,
            config_json=json.dumps(config.__dict__),
            status=SessionStatus.CREATED,
            created_at=datetime.now(timezone.utc),
        )
        store.create_session(session)

        dirs = session_subdirs(session_id)
        for directory in dirs.values():
            directory.mkdir(parents=True, exist_ok=True)

        intake_dir = dirs["intake"]
        ready_dir = dirs["ready"]
        resolution_path = session_dir(session_id) / "resolution.json"

        if args.intake:
            intake_src = Path(args.intake)
            if intake_src.exists():
                if pack.planning_enabled:
                    for file_path in sorted(intake_src.glob("*.md")):
                        shutil.copy2(file_path, intake_dir / file_path.name)
                else:
                    for file_path in sorted(intake_src.glob("*.plan.md")):
                        shutil.copy2(file_path, ready_dir / file_path.name)
                if (intake_src / "resolution.json").exists() and not pack.planning_enabled:
                    shutil.copy2(intake_src / "resolution.json", resolution_path)

        if pack.planning_enabled:
            for intake_file in sorted(intake_dir.glob("*.md")):
                task_id = store._extract_task_id_from_filename(intake_file.name) or intake_file.stem
                store.upsert_task(
                    Task(
                        id=task_id,
                        session_id=session_id,
                        title=intake_file.stem,
                        status=TaskStatus.INTAKE,
                        created_at=datetime.now(timezone.utc),
                    )
                )
        else:
            constraints_map = {constraint.task_id: constraint for constraint in load_resolution(resolution_path)}
            for plan_file in sorted(ready_dir.glob("*.plan.md")):
                task_id = store._extract_task_id_from_filename(plan_file.name)
                if not task_id:
                    metadata = parse_plan_frontmatter(plan_file)
                    task_id = str(metadata.get("PLAN_ID") or plan_file.stem)
                constraint = constraints_map.get(task_id)
                store.create_task(
                    Task(
                        id=task_id,
                        session_id=session_id,
                        title=_extract_title_from_plan(plan_file),
                        status=TaskStatus.READY,
                        plan_filename=plan_file.name,
                        depends_on=constraint.depends_on if constraint else [],
                        anti_affinity=constraint.anti_affinity if constraint else [],
                        exec_order=constraint.exec_order if constraint else 1,
                        created_at=datetime.now(timezone.utc),
                    )
                )

        tasks = store.list_tasks(session_id)
        print(f"\nSession: {session_name} ({session_id})")
        print(f"Pack: {args.pack}")
        print(f"Workers: {num_workers}")
        print(f"Tasks: {len(tasks)}")

        if not tasks and not (pack.planning_enabled and list(intake_dir.glob("*.md"))):
            print("\nNo tasks found. Place .plan.md files in the ready/ directory.")
            print(f"  {ready_dir}")
            return

        print("\nStarting orchestrator...")
        orchestrator = Orchestrator(session_id, store)
        try:
            orchestrator.run_foreground()
        except KeyboardInterrupt:
            print("\nInterrupted. Stopping workers...")
            orchestrator.stop()
    finally:
        store.close()

    summary_store = StateStore()
    summary_store.connect()
    try:
        final_session = summary_store.get_session(session_id)
        final_tasks = summary_store.list_tasks(session_id)
    finally:
        summary_store.close()

    done = sum(1 for task in final_tasks if task.status == TaskStatus.DONE)
    blocked = sum(1 for task in final_tasks if task.status == TaskStatus.BLOCKED)
    print(f"\nSession {final_session.status.value}: {done} done, {blocked} blocked")


def _cmd_serve(args: argparse.Namespace) -> None:
    import threading
    import webbrowser

    import uvicorn

    port = find_free_port(args.port)
    if port != args.port:
        logging.getLogger(__name__).warning("Port %d in use; using %d instead", args.port, port)

    threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    uvicorn.run("cognitive_switchyard.server:app", host="127.0.0.1", port=port)


def _extract_title_from_plan(plan_path: Path) -> str:
    try:
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
    except Exception:
        pass
    return plan_path.stem
