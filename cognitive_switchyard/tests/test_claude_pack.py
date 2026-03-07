from __future__ import annotations

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
