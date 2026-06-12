"""Normalize tool argument dicts from heterogeneous model outputs."""

from __future__ import annotations

from typing import Any


def normalize_args_for_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    cleaned = {k: v for k, v in args.items() if v is not None}

    if name == "write_file":
        if "content" not in cleaned:
            for alias in ("new_string", "text", "body", "file_content"):
                if alias in cleaned:
                    cleaned["content"] = cleaned.pop(alias)
                    break
    elif name == "edit_file":
        if "new_string" not in cleaned and "content" in cleaned:
            cleaned["new_string"] = cleaned.pop("content")
    elif name == "bash":
        if "command" not in cleaned:
            for alias in ("cmd", "script", "shell"):
                if alias in cleaned:
                    cleaned["command"] = cleaned.pop(alias)
                    break
    elif name in ("read_file", "read_document"):
        for key in ("offset", "limit"):
            if key in cleaned:
                cleaned[key] = _coerce_int(cleaned[key])
        for alias in ("file", "filename", "filepath"):
            if "path" not in cleaned and alias in cleaned:
                cleaned["path"] = cleaned.pop(alias)
    elif name == "grep":
        if "pattern" not in cleaned and "query" in cleaned:
            cleaned["pattern"] = cleaned.pop("query")
    elif name == "glob":
        if "pattern" not in cleaned and "glob" in cleaned:
            cleaned["pattern"] = cleaned.pop("glob")
    elif name == "ls":
        if "path" not in cleaned and "directory" in cleaned:
            cleaned["path"] = cleaned.pop("directory")
    elif name == "web_fetch":
        if "url" not in cleaned:
            for alias in ("uri", "link", "href"):
                if alias in cleaned:
                    cleaned["url"] = cleaned.pop(alias)
                    break
        if "max_chars" in cleaned:
            cleaned["max_chars"] = _coerce_int(cleaned["max_chars"])
    elif name == "ask_user":
        if "question" not in cleaned:
            for alias in ("message", "prompt", "query"):
                if alias in cleaned:
                    cleaned["question"] = cleaned.pop(alias)
                    break
    elif name == "todo_write":
        if "todos" not in cleaned and "items" in cleaned:
            cleaned["todos"] = cleaned.pop("items")
    elif name == "skill":
        if "skill_name" not in cleaned:
            for alias in ("name", "skill"):
                if alias in cleaned:
                    cleaned["skill_name"] = cleaned.pop(alias)
                    break
    elif name == "mcp_call":
        if "arguments" not in cleaned and "args" in cleaned:
            cleaned["arguments"] = cleaned.pop("args")
    elif name == "notebook_edit":
        if "cell_index" not in cleaned and "index" in cleaned:
            cleaned["cell_index"] = cleaned.pop("index")
        if "cell_index" in cleaned:
            cleaned["cell_index"] = _coerce_int(cleaned["cell_index"])
        if "new_source" not in cleaned:
            for alias in ("source", "content", "new_string"):
                if alias in cleaned:
                    cleaned["new_source"] = cleaned.pop(alias)
                    break

    return cleaned


def _coerce_int(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return value
