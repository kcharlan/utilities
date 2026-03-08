# Phase 03: Scheduler

**Design doc:** `docs/cognitive_switchyard_design.md`

## Spec

Build the constraint-aware task scheduler. The scheduler determines which tasks are eligible for dispatch based on dependency constraints (DEPENDS_ON), mutual exclusion constraints (ANTI_AFFINITY), and orders eligible tasks by EXEC_ORDER with task ID as tiebreaker.

### Files to create

- `switchyard/scheduler.py`

### Dependencies from prior phases

- `switchyard/models.py` — `Task` dataclass with `depends_on: list[str]`, `anti_affinity: list[str]`, `exec_order: int`, `status: str`

### Constraint types

1. **DEPENDS_ON** (hard dependency): A task is not eligible until ALL tasks in its `depends_on` list have status `"done"`. If any dependency is `"blocked"`, the task is permanently ineligible (it can never run because a dependency will never complete).

2. **ANTI_AFFINITY** (mutual exclusion): A task is not eligible while ANY task in its `anti_affinity` list has status `"active"`. No ordering implied — just "not at the same time." Once the conflicting active task finishes, the blocked task becomes eligible again.

3. **EXEC_ORDER** (tiebreaker): When multiple tasks are eligible, dispatch the one with the lowest `exec_order`. If `exec_order` is tied, dispatch the one with the lowest `id` (lexicographic sort).

### Functions

- `is_eligible(task: Task, all_tasks: list[Task]) -> bool` — Returns True if the task can be dispatched right now. A task is eligible when:
  - Its status is `"ready"` (tasks in any other status are never eligible).
  - All tasks in its `depends_on` list have status `"done"`.
  - No task in its `anti_affinity` list has status `"active"`.

- `next_eligible(ready_tasks: list[Task], all_tasks: list[Task]) -> Optional[Task]` — From the list of ready tasks, find all eligible ones, sort by `(exec_order, id)`, return the first. Returns None if no task is eligible.

- `all_eligible(ready_tasks: list[Task], all_tasks: list[Task]) -> list[Task]` — Return all eligible tasks sorted by `(exec_order, id)`. Used when multiple worker slots are idle.

- `has_unresolvable_deps(task: Task, all_tasks: list[Task]) -> bool` — Returns True if the task depends on a task that is `"blocked"`. This means the task can NEVER become eligible in the current session. The orchestrator uses this to proactively move such tasks to `"blocked"` with a reason like "Dependency t3 is blocked."

- `load_constraint_graph(resolution_json_path: Path) -> dict` — Parse the `resolution.json` file (format defined in design doc Section 5.3). Returns the parsed dict. Used by the orchestrator to populate task constraint fields after resolution.

### Edge cases the implementation must handle

- A task with an empty `depends_on` list is not blocked by dependencies.
- A task with an empty `anti_affinity` list is not blocked by anti-affinity.
- A task whose dependency ID doesn't exist in `all_tasks` should be treated as blocked (defensive — the dependency was somehow lost).
- `next_eligible` with an empty `ready_tasks` list returns None.

## Acceptance tests

```python
# tests/test_phase03_scheduler.py
import json
import pytest
from pathlib import Path

from switchyard.models import Task
from switchyard.scheduler import (
    is_eligible, next_eligible, all_eligible,
    has_unresolvable_deps, load_constraint_graph,
)


def _task(id, status="ready", depends_on=None, anti_affinity=None, exec_order=1):
    return Task(
        id=id, session_id="s1", title=f"Task {id}", status=status,
        depends_on=depends_on or [], anti_affinity=anti_affinity or [],
        exec_order=exec_order, created_at="2026-01-01T00:00:00Z",
    )


# --- Eligibility ---

def test_eligible_no_constraints():
    t = _task("t1")
    assert is_eligible(t, [t]) is True


def test_not_eligible_if_not_ready():
    t = _task("t1", status="done")
    assert is_eligible(t, [t]) is False


def test_blocked_by_pending_dependency():
    dep = _task("t0", status="ready")
    t = _task("t1", depends_on=["t0"])
    assert is_eligible(t, [dep, t]) is False


def test_eligible_when_dependency_done():
    dep = _task("t0", status="done")
    t = _task("t1", depends_on=["t0"])
    assert is_eligible(t, [dep, t]) is True


def test_blocked_by_active_anti_affinity():
    conflict = _task("t2", status="active")
    t = _task("t1", anti_affinity=["t2"])
    assert is_eligible(t, [conflict, t]) is False


def test_eligible_when_anti_affinity_not_active():
    conflict = _task("t2", status="done")  # not active
    t = _task("t1", anti_affinity=["t2"])
    assert is_eligible(t, [conflict, t]) is True


def test_blocked_by_missing_dependency():
    """A dependency that doesn't exist in all_tasks should block the task."""
    t = _task("t1", depends_on=["t_nonexistent"])
    assert is_eligible(t, [t]) is False


# --- Ordering ---

def test_next_eligible_returns_lowest_exec_order():
    t1 = _task("t1", exec_order=3)
    t2 = _task("t2", exec_order=1)
    t3 = _task("t3", exec_order=2)
    result = next_eligible([t1, t2, t3], [t1, t2, t3])
    assert result.id == "t2"


def test_next_eligible_breaks_ties_by_id():
    t1 = _task("t2", exec_order=1)
    t2 = _task("t1", exec_order=1)
    result = next_eligible([t1, t2], [t1, t2])
    assert result.id == "t1"  # "t1" < "t2" lexicographically


def test_next_eligible_returns_none_when_empty():
    assert next_eligible([], []) is None


def test_next_eligible_returns_none_when_all_blocked():
    dep = _task("t0", status="active")
    t = _task("t1", anti_affinity=["t0"])
    assert next_eligible([t], [dep, t]) is None


def test_all_eligible_returns_sorted():
    t1 = _task("t1", exec_order=2)
    t2 = _task("t2", exec_order=1)
    t3 = _task("t3", exec_order=1)  # tied with t2
    result = all_eligible([t1, t2, t3], [t1, t2, t3])
    assert [t.id for t in result] == ["t2", "t3", "t1"]


# --- Unresolvable deps ---

def test_unresolvable_when_dep_blocked():
    dep = _task("t0", status="blocked")
    t = _task("t1", depends_on=["t0"])
    assert has_unresolvable_deps(t, [dep, t]) is True


def test_not_unresolvable_when_dep_ready():
    dep = _task("t0", status="ready")
    t = _task("t1", depends_on=["t0"])
    assert has_unresolvable_deps(t, [dep, t]) is False


def test_not_unresolvable_no_deps():
    t = _task("t1")
    assert has_unresolvable_deps(t, [t]) is False


# --- Constraint graph loading ---

def test_load_constraint_graph(tmp_path):
    graph = {
        "resolved_at": "2026-03-05T14:16:45Z",
        "tasks": [
            {"task_id": "t1", "depends_on": [], "anti_affinity": [], "exec_order": 1},
            {"task_id": "t2", "depends_on": ["t1"], "anti_affinity": ["t3"], "exec_order": 2},
        ],
        "groups": [],
        "conflicts": [],
    }
    path = tmp_path / "resolution.json"
    path.write_text(json.dumps(graph))
    loaded = load_constraint_graph(path)
    assert len(loaded["tasks"]) == 2
    assert loaded["tasks"][1]["depends_on"] == ["t1"]
```
