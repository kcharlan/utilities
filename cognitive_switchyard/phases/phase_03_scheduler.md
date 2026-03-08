# Phase 3: Scheduler

## Spec

Build the constraint-aware task scheduler that determines which tasks are eligible for dispatch. The scheduler is a pure-logic module with no side effects — it reads task state and returns dispatch decisions.

### Dependencies from prior phases

- `switchyard/models.py` — `Task` dataclass with fields: `id`, `status`, `depends_on: list[str]`, `anti_affinity: list[str]`, `exec_order: int`.

### Files to create

**`switchyard/scheduler.py`** — Constraint evaluation and dispatch ordering:

**`is_eligible(task: Task, done_ids: set[str], active_ids: set[str]) -> bool`:**
- A task is eligible when ALL of these are true:
  1. `task.status == "ready"`
  2. Every ID in `task.depends_on` is in `done_ids` (all dependencies completed).
  3. No ID in `task.anti_affinity` is in `active_ids` (no conflicting tasks currently running).
- Returns `True` if all conditions met, `False` otherwise.

**`next_eligible(tasks: list[Task], done_ids: set[str], active_ids: set[str]) -> Optional[Task]`:**
- Filters `tasks` to only eligible ones (using `is_eligible`).
- Sorts eligible tasks by: `exec_order` ascending (primary), then `id` ascending (tiebreaker — lexicographic).
- Returns the first task, or `None` if no tasks are eligible.

**`all_eligible(tasks: list[Task], done_ids: set[str], active_ids: set[str]) -> list[Task]`:**
- Returns ALL eligible tasks, sorted by `exec_order` then `id`. Used when multiple worker slots are free.

**`validate_constraint_graph(tasks: list[Task]) -> list[str]`:**
- Checks the full task set for structural problems. Returns a list of human-readable error strings. Empty list = valid.
- Checks:
  1. **Dangling dependency:** A task's `depends_on` references a task ID that doesn't exist in the task set.
  2. **Self-dependency:** A task lists itself in `depends_on`.
  3. **Circular dependency:** There exists a cycle in the dependency graph. Use iterative topological sort (Kahn's algorithm) — any tasks remaining after the algorithm completes are in a cycle. Report all tasks in the cycle.
  4. **Dangling anti-affinity:** A task's `anti_affinity` references a task ID that doesn't exist in the task set.

**`load_constraint_graph(path: str) -> dict`:**
- Reads and parses a `resolution.json` file. Returns the parsed dict.
- Validates that `"tasks"` key exists and is a list.
- Raises `ValueError` if the file is missing, unparseable, or malformed.

**`apply_constraints(tasks: list[Task], graph: dict) -> list[Task]`:**
- Takes a list of Task objects and a constraint graph dict (from `resolution.json`).
- For each task entry in `graph["tasks"]`, updates the matching Task's `depends_on`, `anti_affinity`, and `exec_order` fields.
- Merges: user-declared dependencies (already on the Task) are preserved. Resolver-added constraints are appended (deduped).
- Returns the updated task list.

## Acceptance tests

```python
"""tests/test_phase03_scheduler.py"""
import json
from pathlib import Path

import pytest

from switchyard.models import Task


def _task(tid, status="ready", depends_on=None, anti_affinity=None, exec_order=0):
    return Task(
        id=tid, session_id="s1", title=f"Task {tid}", status=status,
        depends_on=depends_on or [], anti_affinity=anti_affinity or [],
        exec_order=exec_order, created_at="2026-01-01T00:00:00Z",
    )


# --- is_eligible ---

def test_eligible_no_constraints():
    from switchyard.scheduler import is_eligible
    t = _task("001")
    assert is_eligible(t, done_ids=set(), active_ids=set()) is True


def test_not_eligible_wrong_status():
    from switchyard.scheduler import is_eligible
    t = _task("001", status="staged")
    assert is_eligible(t, done_ids=set(), active_ids=set()) is False


def test_not_eligible_unmet_dependency():
    from switchyard.scheduler import is_eligible
    t = _task("002", depends_on=["001"])
    assert is_eligible(t, done_ids=set(), active_ids=set()) is False


def test_eligible_met_dependency():
    from switchyard.scheduler import is_eligible
    t = _task("002", depends_on=["001"])
    assert is_eligible(t, done_ids={"001"}, active_ids=set()) is True


def test_not_eligible_anti_affinity_active():
    from switchyard.scheduler import is_eligible
    t = _task("002", anti_affinity=["003"])
    assert is_eligible(t, done_ids=set(), active_ids={"003"}) is False


def test_eligible_anti_affinity_not_active():
    from switchyard.scheduler import is_eligible
    t = _task("002", anti_affinity=["003"])
    assert is_eligible(t, done_ids={"003"}, active_ids=set()) is True


def test_not_eligible_partial_deps():
    """If a task depends on [A, B] and only A is done, it's NOT eligible."""
    from switchyard.scheduler import is_eligible
    t = _task("003", depends_on=["001", "002"])
    assert is_eligible(t, done_ids={"001"}, active_ids=set()) is False


# --- next_eligible ---

def test_next_eligible_respects_exec_order():
    from switchyard.scheduler import next_eligible
    tasks = [_task("002", exec_order=2), _task("001", exec_order=1)]
    result = next_eligible(tasks, done_ids=set(), active_ids=set())
    assert result.id == "001"


def test_next_eligible_tiebreak_by_id():
    from switchyard.scheduler import next_eligible
    tasks = [_task("003", exec_order=1), _task("001", exec_order=1)]
    result = next_eligible(tasks, done_ids=set(), active_ids=set())
    assert result.id == "001"


def test_next_eligible_none_available():
    from switchyard.scheduler import next_eligible
    tasks = [_task("001", status="done"), _task("002", depends_on=["999"])]
    result = next_eligible(tasks, done_ids=set(), active_ids=set())
    assert result is None


def test_all_eligible_returns_sorted():
    from switchyard.scheduler import all_eligible
    tasks = [
        _task("003", exec_order=2),
        _task("001", exec_order=1),
        _task("002", exec_order=1),
    ]
    result = all_eligible(tasks, done_ids=set(), active_ids=set())
    assert [t.id for t in result] == ["001", "002", "003"]


# --- validate_constraint_graph ---

def test_validate_no_errors():
    from switchyard.scheduler import validate_constraint_graph
    tasks = [_task("001"), _task("002", depends_on=["001"])]
    assert validate_constraint_graph(tasks) == []


def test_validate_dangling_dependency():
    from switchyard.scheduler import validate_constraint_graph
    tasks = [_task("001", depends_on=["999"])]
    errors = validate_constraint_graph(tasks)
    assert any("999" in e for e in errors)


def test_validate_self_dependency():
    from switchyard.scheduler import validate_constraint_graph
    tasks = [_task("001", depends_on=["001"])]
    errors = validate_constraint_graph(tasks)
    assert any("self" in e.lower() or "001" in e for e in errors)


def test_validate_circular_dependency():
    from switchyard.scheduler import validate_constraint_graph
    tasks = [
        _task("001", depends_on=["003"]),
        _task("002", depends_on=["001"]),
        _task("003", depends_on=["002"]),
    ]
    errors = validate_constraint_graph(tasks)
    assert any("cycl" in e.lower() or "circular" in e.lower() for e in errors)


def test_validate_dangling_anti_affinity():
    from switchyard.scheduler import validate_constraint_graph
    tasks = [_task("001", anti_affinity=["999"])]
    errors = validate_constraint_graph(tasks)
    assert any("999" in e for e in errors)


# --- load_constraint_graph ---

def test_load_constraint_graph_valid(tmp_path):
    from switchyard.scheduler import load_constraint_graph
    graph = {"tasks": [{"task_id": "001", "depends_on": [], "anti_affinity": [], "exec_order": 1}]}
    p = tmp_path / "resolution.json"
    p.write_text(json.dumps(graph))
    result = load_constraint_graph(str(p))
    assert len(result["tasks"]) == 1


def test_load_constraint_graph_missing_file():
    from switchyard.scheduler import load_constraint_graph
    with pytest.raises(ValueError):
        load_constraint_graph("/nonexistent/resolution.json")


def test_load_constraint_graph_malformed(tmp_path):
    from switchyard.scheduler import load_constraint_graph
    (tmp_path / "bad.json").write_text('{"not_tasks": []}')
    with pytest.raises(ValueError):
        load_constraint_graph(str(tmp_path / "bad.json"))


# --- apply_constraints ---

def test_apply_constraints_merges():
    from switchyard.scheduler import apply_constraints
    tasks = [
        _task("001", depends_on=["000"]),  # user-declared dep preserved
        _task("002"),
    ]
    graph = {"tasks": [
        {"task_id": "001", "depends_on": ["000", "002"], "anti_affinity": ["002"], "exec_order": 3},
        {"task_id": "002", "depends_on": [], "anti_affinity": [], "exec_order": 1},
    ]}
    result = apply_constraints(tasks, graph)
    t1 = next(t for t in result if t.id == "001")
    assert "000" in t1.depends_on  # user-declared preserved
    assert "002" in t1.depends_on  # resolver-added
    assert len(t1.depends_on) == 2  # deduped
    assert t1.anti_affinity == ["002"]
    assert t1.exec_order == 3
```
