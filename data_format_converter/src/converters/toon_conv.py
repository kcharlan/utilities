import re
from typing import Any, Dict

class ToonUnavailable(Exception):
    pass

def load_toon(text: str) -> Dict[str, Any]:
    """
    Parses a TOON string using a lightweight, recursive parser.
    """
    data = {}
    # Regex to find key-value pairs, supporting nested inline objects and lists.
    # This is a simplified regex and may not cover all edge cases.
    pattern = re.compile(r'([\w\s]+):\s*({.*?}|\[.*?\]|".*?"|[^,\n}]+)', re.DOTALL)
    
    text = text.strip()
    if text.startswith('{') and text.endswith('}'):
        text = text[1:-1].strip()

    for match in pattern.finditer(text):
        key, value_str = match.groups()
        data[key.strip()] = _parse_value(value_str.strip())
        
    return data

def _parse_value(value_str: str) -> Any:
    """Helper to parse a TOON value string."""
    value_str = value_str.strip()
    if value_str.startswith('"') and value_str.endswith('"'):
        return value_str[1:-1]
    if value_str == 'true':
        return True
    if value_str == 'false':
        return False
    if value_str == 'null':
        return None
    if value_str.startswith('[') and value_str.endswith(']'):
        list_content = value_str[1:-1].strip()
        if not list_content:
            return []
        # This is a very basic list parser, especially for objects.
        # It will not handle complex cases.
        if '{' in list_content:
             # It's a list of objects, let's try to parse them one by one
            items = []
            # This regex is a hack to split objects in a list
            object_strs = re.findall(r'\{.*?\}', list_content)
            for obj_str in object_strs:
                items.append(load_toon(obj_str))
            return items
        else:
            # It's a list of primitives
            return [_parse_value(item.strip()) for item in list_content.split(',')]

    if value_str.startswith('{') and value_str.endswith('}'):
        return load_toon(value_str) # Recursive call
    try:
        # Try to convert to number if it's not a string literal
        if not (value_str.startswith('"') and value_str.endswith('"')):
            return int(value_str)
    except ValueError:
        try:
            if not (value_str.startswith('"') and value_str.endswith('"')):
                return float(value_str)
        except ValueError:
            return value_str # It's a string
    return value_str


def dump_toon(obj: Any) -> str:
    """
    Dumps a Python object to a TOON string using a lightweight, built-in dumper.
    """
    if not isinstance(obj, dict):
        raise ToonUnavailable("Built-in TOON dumper only supports dictionaries as the root object.")
    
    lines = []
    for key, value in sorted(obj.items()):
        lines.append(f"{key}: {_dump_value(value)}")
        
    return "\n".join(lines)

def _dump_value(value: Any) -> str:
    """Helper to dump a Python value to a TOON string value."""
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if value is None:
        return 'null'
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return f"[{', '.join(_dump_value(item) for item in value)}]"
    if isinstance(value, dict):
        # Always dump nested objects inline
        return f"{{ {dump_toon(value)} }}"
    raise ToonUnavailable(f"Unsupported type for TOON conversion: {type(value)}")