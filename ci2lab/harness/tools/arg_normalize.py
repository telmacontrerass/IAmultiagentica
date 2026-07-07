"""Normalize tool argument dicts from heterogeneous model outputs."""

from __future__ import annotations

from typing import Any

#: Argument keys whose values may arrive wrapped in stray quotes/backticks and
#: should be unquoted before use.
_QUOTED_STRING_KEYS: tuple[str, ...] = (
    "path",
    "output_path",
    "url",
    "directory",
    "file",
    "filename",
    "filepath",
)


def _strip_surrounding_quotes(value: Any) -> Any:
    """Drop matching surrounding quotes/backticks a model wrapped a path in.

    Models often emit a path as `'/abs/file.pdf'` (quotes included). Without
    stripping, the leading quote makes the path look relative and it gets joined
    to the workspace, producing a bogus `cwd/'/abs/file.pdf'` that never exists.
    """
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    while len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in "'\"`":
        stripped = stripped[1:-1].strip()
    return stripped


def normalize_args_for_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Normalize an argument dict for a specific tool.

    Strips ``None`` values, unquotes path-like keys and resolves the per-tool
    aliases that different models tend to emit (for example mapping ``cmd`` to
    ``command`` for ``bash`` or ``diff`` to ``patch`` for ``apply_patch``).
    Numeric arguments such as ``offset`` and ``max_results`` are coerced to
    ``int`` where possible.

    Args:
        name: Canonical tool name selecting which alias rules to apply.
        args: Raw argument mapping from the model.

    Returns:
        A new normalized argument mapping.
    """
    if not isinstance(args, dict):
        # A model sometimes emits a bare JSON array/scalar as a tool's whole
        # argument payload (e.g. ```todo_write\n[{...}]```). Wrap it into the
        # tool's primary argument instead of crashing on ``.items()``; unknown
        # shapes collapse to ``{}`` so the tool reports a clean missing-argument
        # error rather than raising ``AttributeError``.
        if isinstance(args, list) and name == "todo_write":
            return {"todos": args}
        return {}
    cleaned = {k: v for k, v in args.items() if v is not None}
    for key in _QUOTED_STRING_KEYS:
        if key in cleaned:
            cleaned[key] = _strip_surrounding_quotes(cleaned[key])

    if name in ("write_file", "write_docx"):
        if "content" not in cleaned:
            for alias in ("new_string", "text", "body", "file_content"):
                if alias in cleaned:
                    cleaned["content"] = cleaned.pop(alias)
                    break
    elif name == "write_pptx":
        if "output_path" not in cleaned:
            for alias in ("path", "output", "file", "filename", "filepath"):
                if alias in cleaned:
                    cleaned["output_path"] = cleaned.pop(alias)
                    break
    elif name == "edit_file":
        if "new_string" not in cleaned and "content" in cleaned:
            cleaned["new_string"] = cleaned.pop("content")
    elif name == "apply_patch":
        if "patch" not in cleaned:
            for alias in ("diff", "unified_diff", "content", "body"):
                if alias in cleaned:
                    cleaned["patch"] = cleaned.pop(alias)
                    break
    elif name == "bash":
        if "command" not in cleaned:
            for alias in ("cmd", "script", "shell"):
                if alias in cleaned:
                    cleaned["command"] = cleaned.pop(alias)
                    break
    elif name in ("read_file", "read_document", "create_quiz_questions"):
        for key in ("offset", "limit"):
            if key in cleaned:
                cleaned[key] = _coerce_int(cleaned[key])
        for alias in ("file", "filename", "filepath"):
            if "path" not in cleaned and alias in cleaned:
                cleaned["path"] = cleaned.pop(alias)
        if name == "create_quiz_questions":
            if "question_count" not in cleaned:
                for alias in ("questions", "num_questions", "n_questions", "n_preguntas"):
                    if alias in cleaned:
                        cleaned["question_count"] = cleaned.pop(alias)
                        break
            if "options_per_question" not in cleaned:
                for alias in ("options", "choices", "num_options", "opciones"):
                    if alias in cleaned:
                        cleaned["options_per_question"] = cleaned.pop(alias)
                        break
            for key in ("question_count", "options_per_question"):
                if key in cleaned:
                    cleaned[key] = _coerce_int(cleaned[key])
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
    elif name == "web_search":
        if "query" not in cleaned:
            for alias in ("raw", "q", "search", "prompt"):
                if alias in cleaned:
                    cleaned["query"] = cleaned.pop(alias)
                    break
        if "max_results" in cleaned:
            cleaned["max_results"] = _coerce_int(cleaned["max_results"])
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
    """Convert digit-only strings to ``int``, leaving other values untouched."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return value
