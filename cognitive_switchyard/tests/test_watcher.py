from __future__ import annotations

from cognitive_switchyard.watcher import DirectoryWatcher, StatusFileWatcher


class TestDirectoryWatcher:
    def test_first_check_returns_all(self, tmp_path) -> None:
        directory = tmp_path / "intake"
        directory.mkdir()
        (directory / "001_task.md").write_text("content")
        (directory / "002_task.md").write_text("content")
        watcher = DirectoryWatcher(directory, "*.md")
        new, removed = watcher.check()
        assert len(new) == 2
        assert removed == []

    def test_new_file_detected(self, tmp_path) -> None:
        directory = tmp_path / "intake"
        directory.mkdir()
        (directory / "001_task.md").write_text("content")
        watcher = DirectoryWatcher(directory, "*.md")
        watcher.check()
        (directory / "002_task.md").write_text("content")
        new, removed = watcher.check()
        assert len(new) == 1
        assert new[0].name == "002_task.md"
        assert removed == []

    def test_removed_file_detected(self, tmp_path) -> None:
        directory = tmp_path / "intake"
        directory.mkdir()
        task_file = directory / "001_task.md"
        task_file.write_text("content")
        watcher = DirectoryWatcher(directory, "*.md")
        watcher.check()
        task_file.unlink()
        new, removed = watcher.check()
        assert new == []
        assert removed == ["001_task.md"]

    def test_no_changes(self, tmp_path) -> None:
        directory = tmp_path / "intake"
        directory.mkdir()
        (directory / "001_task.md").write_text("content")
        watcher = DirectoryWatcher(directory, "*.md")
        watcher.check()
        assert watcher.check() == ([], [])

    def test_nonexistent_directory(self, tmp_path) -> None:
        watcher = DirectoryWatcher(tmp_path / "nope", "*.md")
        assert watcher.check() == ([], [])

    def test_current_files(self, tmp_path) -> None:
        directory = tmp_path / "dir"
        directory.mkdir()
        (directory / "a.txt").write_text("a")
        (directory / "b.txt").write_text("b")
        assert len(DirectoryWatcher(directory, "*.txt").current_files()) == 2

    def test_reset(self, tmp_path) -> None:
        directory = tmp_path / "dir"
        directory.mkdir()
        (directory / "a.md").write_text("a")
        watcher = DirectoryWatcher(directory, "*.md")
        watcher.check()
        watcher.reset()
        new, _ = watcher.check()
        assert len(new) == 1


class TestStatusFileWatcher:
    def test_find_single_status(self, tmp_path) -> None:
        (tmp_path / "001_task.status").write_text("STATUS: done")
        result = StatusFileWatcher(tmp_path).find_status_file()
        assert result is not None
        assert result.name == "001_task.status"

    def test_find_no_status(self, tmp_path) -> None:
        assert StatusFileWatcher(tmp_path).find_status_file() is None

    def test_find_nonexistent_dir(self, tmp_path) -> None:
        assert StatusFileWatcher(tmp_path / "nope").find_status_file() is None

    def test_find_multiple_returns_newest(self, tmp_path) -> None:
        import time

        (tmp_path / "old.status").write_text("STATUS: blocked")
        time.sleep(0.05)
        (tmp_path / "new.status").write_text("STATUS: done")
        result = StatusFileWatcher(tmp_path).find_status_file()
        assert result.name == "new.status"
