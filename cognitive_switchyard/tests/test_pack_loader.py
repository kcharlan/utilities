from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from cognitive_switchyard.pack_loader import bootstrap_packs, check_scripts_executable, load_pack, reset_pack


@pytest.fixture
def packs_dir(tmp_path, monkeypatch):
    directory = tmp_path / "packs"
    directory.mkdir()
    monkeypatch.setattr("cognitive_switchyard.pack_loader.config.PACKS_DIR", directory)
    return directory


@pytest.fixture
def builtin_dir(tmp_path, monkeypatch):
    directory = tmp_path / "builtin"
    directory.mkdir()
    monkeypatch.setattr("cognitive_switchyard.pack_loader.config.BUILTIN_PACKS_DIR", directory)
    return directory


def _create_pack(base_dir: Path, name: str, extra_yaml: dict | None = None) -> Path:
    pack_path = base_dir / name
    pack_path.mkdir(parents=True, exist_ok=True)
    (pack_path / "scripts").mkdir(exist_ok=True)
    (pack_path / "pack.yaml").write_text(
        yaml.safe_dump({"name": name, "description": f"Test pack {name}", **(extra_yaml or {})})
    )
    return pack_path


class TestLoadPack:
    def test_load_minimal(self, packs_dir) -> None:
        _create_pack(packs_dir, "test-echo")
        cfg = load_pack("test-echo")
        assert cfg.name == "test-echo"
        assert cfg.planning_enabled is False
        assert cfg.execution_max_workers == 2

    def test_load_with_phases(self, packs_dir) -> None:
        _create_pack(
            packs_dir,
            "coding",
            {
                "phases": {
                    "planning": {"enabled": True, "model": "opus", "max_instances": 3},
                    "execution": {"executor": "agent", "model": "sonnet", "max_workers": 4},
                    "verification": {"enabled": True, "command": "pytest", "interval": 3},
                },
                "auto_fix": {"enabled": True, "max_attempts": 3},
            },
        )
        cfg = load_pack("coding")
        assert cfg.planning_enabled is True
        assert cfg.planning_max_instances == 3
        assert cfg.execution_max_workers == 4
        assert cfg.verification_enabled is True
        assert cfg.auto_fix_enabled is True

    def test_load_missing_pack(self, packs_dir) -> None:
        with pytest.raises(ValueError, match="not found"):
            load_pack("nonexistent")

    def test_load_missing_name(self, packs_dir) -> None:
        bad_dir = packs_dir / "bad"
        bad_dir.mkdir()
        (bad_dir / "pack.yaml").write_text("{}")
        with pytest.raises(ValueError, match="missing required"):
            load_pack("bad")


class TestBootstrap:
    def test_bootstrap_copies(self, packs_dir, builtin_dir) -> None:
        _create_pack(builtin_dir, "test-echo")
        bootstrap_packs()
        assert (packs_dir / "test-echo" / "pack.yaml").exists()

    def test_bootstrap_no_overwrite(self, packs_dir, builtin_dir) -> None:
        _create_pack(builtin_dir, "test-echo")
        _create_pack(packs_dir, "test-echo", {"description": "custom"})
        bootstrap_packs()
        data = yaml.safe_load((packs_dir / "test-echo" / "pack.yaml").read_text())
        assert data["description"] == "custom"

    def test_reset_pack(self, packs_dir, builtin_dir) -> None:
        _create_pack(builtin_dir, "test-echo", {"description": "factory"})
        _create_pack(packs_dir, "test-echo", {"description": "custom"})
        assert reset_pack("test-echo")
        data = yaml.safe_load((packs_dir / "test-echo" / "pack.yaml").read_text())
        assert data["description"] == "factory"


class TestScriptChecks:
    def test_all_executable(self, packs_dir) -> None:
        pack_path = _create_pack(packs_dir, "good")
        script = pack_path / "scripts" / "execute"
        script.write_text("#!/bin/bash\necho hi\n")
        script.chmod(0o755)
        assert check_scripts_executable("good") == []

    def test_non_executable(self, packs_dir) -> None:
        pack_path = _create_pack(packs_dir, "bad")
        script = pack_path / "scripts" / "execute"
        script.write_text("#!/bin/bash\necho hi\n")
        script.chmod(0o644)
        failures = check_scripts_executable("bad")
        assert len(failures) == 1
        assert "execute" in failures[0][0]
        assert "chmod +x" in failures[0][1]
