from __future__ import annotations

import os
from pathlib import Path


def test_root_switchyard_script_exists_and_is_executable() -> None:
    script = Path(__file__).resolve().parent.parent / "switchyard"
    assert script.exists()
    assert os.access(script, os.X_OK)
    text = script.read_text()
    assert "cognitive_switchyard.__main__" in text


def test_html_template_contains_key_views() -> None:
    from cognitive_switchyard.html_template import get_html

    html = get_html()
    assert "COGNITIVE SWITCHYARD" in html
    assert "Task Feed" in html
    assert "Session History" in html
    assert "reactflow" in html.lower()
