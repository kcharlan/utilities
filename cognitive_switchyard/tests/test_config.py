from __future__ import annotations

from pathlib import Path

from cognitive_switchyard.config import (
    GlobalConfig,
    SessionConfig,
    SWITCHYARD_HOME,
    ensure_directories,
    session_subdirs,
)


def test_paths_are_pathlib() -> None:
    assert isinstance(SWITCHYARD_HOME, Path)


def test_global_config_defaults() -> None:
    cfg = GlobalConfig()
    assert cfg.retention_days == 30
    assert cfg.default_workers == 2


def test_global_config_save_load(tmp_path, monkeypatch) -> None:
    config_file = tmp_path / "config.yaml"
    monkeypatch.setattr("cognitive_switchyard.config.CONFIG_FILE", config_file)
    cfg = GlobalConfig(retention_days=7, default_workers=4)
    cfg.save()
    assert config_file.exists()
    loaded = GlobalConfig.load()
    assert loaded.retention_days == 7
    assert loaded.default_workers == 4


def test_session_config_defaults() -> None:
    cfg = SessionConfig(pack_name="test", session_name="run-1")
    assert cfg.num_workers == 2
    assert cfg.task_idle_timeout == 300


def test_session_subdirs() -> None:
    dirs = session_subdirs("abc-123")
    assert "intake" in dirs
    assert "ready" in dirs
    assert "done" in dirs
    assert dirs["intake"].name == "intake"


def test_ensure_directories(tmp_path, monkeypatch) -> None:
    home = tmp_path / ".cognitive_switchyard"
    monkeypatch.setattr("cognitive_switchyard.config.SWITCHYARD_HOME", home)
    monkeypatch.setattr("cognitive_switchyard.config.PACKS_DIR", home / "packs")
    monkeypatch.setattr("cognitive_switchyard.config.SESSIONS_DIR", home / "sessions")
    ensure_directories()
    assert (home / "packs").is_dir()
    assert (home / "sessions").is_dir()
