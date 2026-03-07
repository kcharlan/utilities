from __future__ import annotations

from pathlib import Path

from cognitive_switchyard.pack_loader import invoke_hook


def run_planner_script(
    pack_name: str,
    script_relative_path: str,
    intake_path: Path,
    staging_dir: Path,
    review_dir: Path,
    timeout: int = 120,
) -> None:
    """Run a script-backed planner for a single claimed intake item."""
    result = invoke_hook(
        pack_name,
        script_relative_path,
        args=[str(intake_path), str(staging_dir), str(review_dir)],
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "planner script failed")
