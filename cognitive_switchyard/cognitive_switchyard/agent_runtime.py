from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Mapping, Optional

from cognitive_switchyard.pack_loader import pack_dir

DEFAULT_ALLOWED_TOOLS = "Edit,Read,Write,Bash,Glob,Grep,MultiEdit"


def load_prompt(pack_name: str, prompt_relative_path: str) -> str:
    prompt_path = pack_dir(pack_name) / prompt_relative_path
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    return prompt_path.read_text()


def render_prompt(base_prompt: str, context: Mapping[str, object]) -> str:
    lines = [base_prompt.rstrip(), "", "## SWITCHYARD_CONTEXT"]
    for key, value in context.items():
        if value is None:
            continue
        lines.append(f"{key}: {value}")
    return "\n".join(lines).strip() + "\n"


def build_agent_command(
    *,
    model: str,
    prompt: str,
    allowed_tools: str = DEFAULT_ALLOWED_TOOLS,
) -> list[str]:
    agent_bin = os.environ.get("COGNITIVE_SWITCHYARD_AGENT_BIN", "claude")
    return [
        agent_bin,
        "--dangerously-skip-permissions",
        "--model",
        model,
        "-p",
        prompt,
        "--allowedTools",
        allowed_tools,
    ]


def run_agent(
    *,
    pack_name: str,
    prompt_relative_path: str,
    model: str,
    context: Mapping[str, object],
    cwd: Optional[str | Path] = None,
    timeout: int = 300,
    env: Optional[dict[str, str]] = None,
) -> subprocess.CompletedProcess[str]:
    prompt = render_prompt(load_prompt(pack_name, prompt_relative_path), context)
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    return subprocess.run(
        build_agent_command(model=model, prompt=prompt),
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=process_env,
    )
