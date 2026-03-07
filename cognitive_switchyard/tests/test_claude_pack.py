from __future__ import annotations

import subprocess
from pathlib import Path

from cognitive_switchyard.pack_loader import check_scripts_executable, load_pack


def test_claude_code_pack_loads() -> None:
    pack = load_pack("claude-code")
    assert pack.name == "claude-code"
    assert pack.planning_enabled is True
    assert pack.execution_executor == "agent"
    assert pack.verification_enabled is True
    assert pack.auto_fix_enabled is True


def test_claude_code_scripts_are_executable() -> None:
    assert check_scripts_executable("claude-code") == []


def test_claude_code_prompts_do_not_reference_legacy_paths() -> None:
    prompts_dir = Path(__file__).resolve().parent.parent / "packs" / "claude-code" / "prompts"
    for prompt_path in prompts_dir.glob("*.md"):
        text = prompt_path.read_text()
        assert "/Users/" not in text
        assert "work/planning/" not in text
        assert "work/execution/" not in text
        assert "execution/active/" not in text
        assert "benefit_specification_engine" not in text


def test_claude_code_planner_prompt_preserves_metadata_nuance() -> None:
    planner_prompt = (
        Path(__file__).resolve().parent.parent / "packs" / "claude-code" / "prompts" / "planner.md"
    ).read_text()
    assert "PRIORITY: normal | high" in planner_prompt
    assert 'DEPENDS_ON: <plan IDs if sequential dependency, else "none">' in planner_prompt
    assert "FULL_TEST_AFTER: yes | no" in planner_prompt
    assert "## Questions for Review" in planner_prompt
    assert "## Operator Actions" in planner_prompt
    assert "## Testing" in planner_prompt


def test_claude_code_isolation_hooks_merge_and_cleanup(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "branch", "-M", "dev"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "demo.txt").write_text("base\n")
    subprocess.run(["git", "add", "demo.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)

    session_dir = tmp_path / "session"
    session_dir.mkdir()
    scripts_dir = Path(__file__).resolve().parent.parent / "packs" / "claude-code" / "scripts"

    start = subprocess.run(
        [str(scripts_dir / "isolate_start"), "0", "001", str(session_dir)],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    worktree = Path(start.stdout.strip())
    assert worktree.exists()

    (worktree / "demo.txt").write_text("changed\n")
    subprocess.run(["git", "add", "demo.txt"], cwd=worktree, check=True)
    subprocess.run(
        ["git", "commit", "-m", "worker change"],
        cwd=worktree,
        check=True,
        capture_output=True,
        text=True,
    )

    subprocess.run(
        [str(scripts_dir / "isolate_end"), str(worktree), "done", "001"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )

    assert (repo / "demo.txt").read_text() == "changed\n"
    assert not worktree.exists()
    history = subprocess.run(
        ["git", "log", "--oneline", "-1"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "feat(pipeline): plan 001" in history.stdout


def test_claude_code_isolation_start_refuses_main(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "demo.txt").write_text("base\n")
    subprocess.run(["git", "add", "demo.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)

    session_dir = tmp_path / "session"
    session_dir.mkdir()
    scripts_dir = Path(__file__).resolve().parent.parent / "packs" / "claude-code" / "scripts"
    result = subprocess.run(
        [str(scripts_dir / "isolate_start"), "0", "001", str(session_dir)],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Refusing to operate on main" in result.stderr


def test_claude_code_isolation_end_preserves_blocked_worktree(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "branch", "-M", "dev"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "demo.txt").write_text("base\n")
    subprocess.run(["git", "add", "demo.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)

    session_dir = tmp_path / "session"
    session_dir.mkdir()
    scripts_dir = Path(__file__).resolve().parent.parent / "packs" / "claude-code" / "scripts"
    start = subprocess.run(
        [str(scripts_dir / "isolate_start"), "0", "001", str(session_dir)],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    worktree = Path(start.stdout.strip())
    subprocess.run(
        [str(scripts_dir / "isolate_end"), str(worktree), "blocked", "001"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    assert worktree.exists()
