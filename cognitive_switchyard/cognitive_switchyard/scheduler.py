from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from cognitive_switchyard.models import Constraint, Task, TaskStatus

logger = logging.getLogger(__name__)


def load_resolution(resolution_path: Path) -> list[Constraint]:
    if not resolution_path.exists():
        logger.warning("No resolution.json found at %s", resolution_path)
        return []

    with resolution_path.open() as handle:
        data = json.load(handle)

    return [
        Constraint(
            task_id=entry["task_id"],
            depends_on=entry.get("depends_on", []),
            anti_affinity=entry.get("anti_affinity", []),
            exec_order=entry.get("exec_order", 1),
        )
        for entry in data.get("tasks", [])
    ]


def is_task_eligible(task: Task, all_tasks: list[Task]) -> bool:
    if task.status != TaskStatus.READY:
        return False

    status_map = {item.id: item.status for item in all_tasks}

    for dependency in task.depends_on:
        if status_map.get(dependency) != TaskStatus.DONE:
            return False

    for conflict in task.anti_affinity:
        if status_map.get(conflict) == TaskStatus.ACTIVE:
            return False

    return True


def find_next_eligible(all_tasks: list[Task]) -> Optional[Task]:
    eligible = [task for task in all_tasks if is_task_eligible(task, all_tasks)]
    if not eligible:
        return None
    eligible.sort(key=lambda task: (task.exec_order, task.id))
    return eligible[0]


def detect_deadlock(all_tasks: list[Task]) -> bool:
    if any(task.status == TaskStatus.ACTIVE for task in all_tasks):
        return False

    pending = [task for task in all_tasks if task.status not in (TaskStatus.DONE, TaskStatus.BLOCKED)]
    if not pending:
        return False

    return not any(is_task_eligible(task, all_tasks) for task in pending)


def count_pending(all_tasks: list[Task]) -> int:
    return sum(
        1
        for task in all_tasks
        if task.status not in (TaskStatus.DONE, TaskStatus.BLOCKED)
    )
