from __future__ import annotations

import json

from cognitive_switchyard.models import Task, TaskStatus
from cognitive_switchyard.scheduler import count_pending, detect_deadlock, find_next_eligible, is_task_eligible, load_resolution


def _task(tid: str, status=TaskStatus.READY, depends=None, anti=None, order: int = 1) -> Task:
    return Task(
        id=tid,
        session_id="s1",
        title=f"Task {tid}",
        status=status,
        depends_on=depends or [],
        anti_affinity=anti or [],
        exec_order=order,
    )


class TestEligibility:
    def test_ready_no_constraints(self) -> None:
        task = _task("001")
        assert is_task_eligible(task, [task])

    def test_not_ready(self) -> None:
        task = _task("001", status=TaskStatus.DONE)
        assert not is_task_eligible(task, [task])

    def test_dep_satisfied(self) -> None:
        dep = _task("001", status=TaskStatus.DONE)
        task = _task("002", depends=["001"])
        assert is_task_eligible(task, [dep, task])

    def test_dep_not_satisfied(self) -> None:
        dep = _task("001", status=TaskStatus.READY)
        task = _task("002", depends=["001"])
        assert not is_task_eligible(task, [dep, task])

    def test_dep_blocked(self) -> None:
        dep = _task("001", status=TaskStatus.BLOCKED)
        task = _task("002", depends=["001"])
        assert not is_task_eligible(task, [dep, task])

    def test_anti_affinity_idle(self) -> None:
        aa = _task("001", status=TaskStatus.READY)
        task = _task("002", anti=["001"])
        assert is_task_eligible(task, [aa, task])

    def test_anti_affinity_active(self) -> None:
        aa = _task("001", status=TaskStatus.ACTIVE)
        task = _task("002", anti=["001"])
        assert not is_task_eligible(task, [aa, task])

    def test_anti_affinity_done(self) -> None:
        aa = _task("001", status=TaskStatus.DONE)
        task = _task("002", anti=["001"])
        assert is_task_eligible(task, [aa, task])

    def test_mixed_constraints(self) -> None:
        dep = _task("001", status=TaskStatus.DONE)
        aa = _task("003", status=TaskStatus.ACTIVE)
        task = _task("002", depends=["001"], anti=["003"])
        assert not is_task_eligible(task, [dep, task, aa])

    def test_mixed_constraints_all_clear(self) -> None:
        dep = _task("001", status=TaskStatus.DONE)
        aa = _task("003", status=TaskStatus.DONE)
        task = _task("002", depends=["001"], anti=["003"])
        assert is_task_eligible(task, [dep, task, aa])


class TestFindNextEligible:
    def test_picks_lowest_exec_order(self) -> None:
        assert find_next_eligible([_task("001", order=2), _task("002", order=1)]).id == "002"

    def test_picks_lowest_id_on_tie(self) -> None:
        assert find_next_eligible([_task("002"), _task("001")]).id == "001"

    def test_skips_ineligible(self) -> None:
        dep = _task("001", status=TaskStatus.READY)
        task = _task("002", depends=["001"])
        assert find_next_eligible([dep, task]).id == "001"

    def test_none_eligible(self) -> None:
        dep = _task("001", status=TaskStatus.ACTIVE)
        task = _task("002", depends=["001"])
        assert find_next_eligible([dep, task]) is None


class TestDeadlock:
    def test_no_deadlock_workers_active(self) -> None:
        assert not detect_deadlock([_task("001", status=TaskStatus.ACTIVE)])

    def test_no_deadlock_all_done(self) -> None:
        assert not detect_deadlock([_task("001", status=TaskStatus.DONE)])

    def test_deadlock_pending_but_deps_blocked(self) -> None:
        dep = _task("001", status=TaskStatus.BLOCKED)
        task = _task("002", depends=["001"])
        assert detect_deadlock([dep, task])

    def test_no_deadlock_eligible_exists(self) -> None:
        assert not detect_deadlock([_task("001"), _task("002")])


class TestLoadResolution:
    def test_load_resolution_json(self, tmp_path) -> None:
        payload = {
            "resolved_at": "2026-03-05T14:16:45Z",
            "tasks": [
                {"task_id": "038", "depends_on": [], "anti_affinity": [], "exec_order": 1},
                {"task_id": "040", "depends_on": [], "anti_affinity": ["041", "042"], "exec_order": 1},
                {"task_id": "041", "depends_on": ["038"], "anti_affinity": ["040"], "exec_order": 2},
            ],
            "groups": [],
            "conflicts": [],
        }
        resolution_path = tmp_path / "resolution.json"
        resolution_path.write_text(json.dumps(payload))
        constraints = load_resolution(resolution_path)
        assert len(constraints) == 3
        assert constraints[1].anti_affinity == ["041", "042"]
        assert constraints[2].depends_on == ["038"]
        assert constraints[2].exec_order == 2

    def test_load_missing_file(self, tmp_path) -> None:
        assert load_resolution(tmp_path / "missing.json") == []


class TestCountPending:
    def test_counts(self) -> None:
        tasks = [
            _task("001", status=TaskStatus.READY),
            _task("002", status=TaskStatus.ACTIVE),
            _task("003", status=TaskStatus.DONE),
            _task("004", status=TaskStatus.BLOCKED),
            _task("005", status=TaskStatus.READY),
        ]
        assert count_pending(tasks) == 3
