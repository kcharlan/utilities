from __future__ import annotations

import json
from typing import Any


def safe_load(stream: str | Any) -> Any:
    text = stream.read() if hasattr(stream, "read") else str(stream)
    if not text.strip():
        return None

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return _parse_yaml_mapping(text)


def safe_dump(data: Any, stream: Any = None, default_flow_style: bool = False) -> str | None:
    dumped = json.dumps(data, indent=2)
    if stream is not None:
        stream.write(dumped)
        return None
    return dumped


def dump(data: Any, stream: Any = None, default_flow_style: bool = False) -> str | None:
    return safe_dump(data, stream=stream, default_flow_style=default_flow_style)


def _parse_yaml_mapping(text: str) -> dict[str, Any]:
    lines = [line.rstrip("\n") for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    parsed, _ = _parse_block(lines, 0, 0)
    return parsed


def _parse_block(lines: list[str], start: int, indent: int) -> tuple[Any, int]:
    mapping: dict[str, Any] = {}
    index = start
    while index < len(lines):
        line = lines[index]
        current_indent = len(line) - len(line.lstrip(" "))
        if current_indent < indent:
            break
        if current_indent > indent:
            raise ValueError(f"Unexpected indentation: {line}")

        stripped = line.strip()
        if stripped.startswith("- "):
            items, index = _parse_list(lines, index, indent)
            return items, index

        key, _, raw_value = stripped.partition(":")
        if not _:
            raise ValueError(f"Invalid YAML line: {line}")

        value = raw_value.strip()
        if value == "":
            if index + 1 >= len(lines):
                mapping[key] = {}
                index += 1
                continue
            next_indent = len(lines[index + 1]) - len(lines[index + 1].lstrip(" "))
            if next_indent <= current_indent:
                mapping[key] = {}
                index += 1
                continue
            nested, index = _parse_block(lines, index + 1, next_indent)
            mapping[key] = nested
            continue

        mapping[key] = _parse_scalar(value)
        index += 1
    return mapping, index


def _parse_list(lines: list[str], start: int, indent: int) -> tuple[list[Any], int]:
    items: list[Any] = []
    index = start
    while index < len(lines):
        line = lines[index]
        current_indent = len(line) - len(line.lstrip(" "))
        if current_indent < indent:
            break
        if current_indent != indent or not line.strip().startswith("- "):
            break

        item_text = line.strip()[2:].strip()
        if not item_text:
            nested, index = _parse_block(lines, index + 1, indent + 2)
            items.append(nested)
            continue

        if ":" in item_text:
            key, _, value = item_text.partition(":")
            item: dict[str, Any] = {key.strip(): _parse_scalar(value.strip()) if value.strip() else {}}
            index += 1
            while index < len(lines):
                next_line = lines[index]
                next_indent = len(next_line) - len(next_line.lstrip(" "))
                if next_indent <= indent:
                    break
                nested_key, _, nested_value = next_line.strip().partition(":")
                item[nested_key.strip()] = _parse_scalar(nested_value.strip()) if nested_value.strip() else {}
                index += 1
            items.append(item)
            continue

        items.append(_parse_scalar(item_text))
        index += 1
    return items, index


def _parse_scalar(value: str) -> Any:
    if value in {"[]", "[ ]"}:
        return []
    if value in {"{}", "{ }"}:
        return {}
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if value.lower() in {"null", "none"}:
        return None
    if value.startswith(("\"", "'")) and value.endswith(("\"", "'")):
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
        return value
