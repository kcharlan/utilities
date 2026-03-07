from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class DirectoryWatcher:
    """Poll a directory for file additions and removals."""

    def __init__(self, directory: Path, glob_pattern: str = "*"):
        self._directory = directory
        self._pattern = glob_pattern
        self._previous: set[str] = set()
        self._initialized = False

    @property
    def directory(self) -> Path:
        return self._directory

    def check(self) -> tuple[list[Path], list[str]]:
        if not self._directory.exists():
            if self._previous:
                removed = sorted(self._previous)
                self._previous = set()
                self._initialized = False
                return [], removed
            return [], []

        current_files = {
            path.name: path
            for path in self._directory.glob(self._pattern)
            if path.is_file()
        }
        current_names = set(current_files)

        if not self._initialized:
            self._previous = current_names
            self._initialized = True
            return [current_files[name] for name in sorted(current_names)], []

        new_names = current_names - self._previous
        removed_names = self._previous - current_names
        self._previous = current_names
        return [current_files[name] for name in sorted(new_names)], sorted(removed_names)

    def current_files(self) -> list[Path]:
        if not self._directory.exists():
            return []
        return sorted(
            path for path in self._directory.glob(self._pattern) if path.is_file()
        )

    def reset(self) -> None:
        self._previous = set()
        self._initialized = False


class StatusFileWatcher:
    """Watch a worker slot for a .status file."""

    def __init__(self, directory: Path):
        self._directory = directory

    def find_status_file(self) -> Optional[Path]:
        if not self._directory.exists():
            return None
        status_files = list(self._directory.glob("*.status"))
        if len(status_files) == 1:
            return status_files[0]
        if len(status_files) > 1:
            logger.warning(
                "Multiple .status files in %s: %s",
                self._directory,
                [path.name for path in status_files],
            )
            return max(status_files, key=lambda path: path.stat().st_mtime)
        return None
