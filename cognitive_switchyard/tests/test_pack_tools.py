from __future__ import annotations

from pathlib import Path

from cognitive_switchyard.pack_loader import scaffold_pack, validate_pack_path


def test_scaffold_pack(tmp_path) -> None:
    pack_path = scaffold_pack("demo-pack", destination=tmp_path)
    assert (pack_path / "pack.yaml").exists()
    assert (pack_path / "scripts" / "execute").exists()
    assert (pack_path / "templates" / "intake.md").exists()


def test_validate_pack_path_good(tmp_path) -> None:
    pack_path = scaffold_pack("demo-pack", destination=tmp_path)
    assert validate_pack_path(pack_path) == []


def test_validate_pack_path_bad(tmp_path) -> None:
    bad_path = tmp_path / "bad-pack"
    bad_path.mkdir()
    (bad_path / "pack.yaml").write_text("name: bad-pack\nphases:\n  execution:\n    executor: shell\n    command: scripts/missing\n")
    issues = validate_pack_path(bad_path)
    assert any("does not exist" in issue for issue in issues)
