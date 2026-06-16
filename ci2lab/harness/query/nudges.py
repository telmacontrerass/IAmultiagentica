"""Retry hints and follow-ups for special tool scenarios (PDF, etc.)."""

from __future__ import annotations

import re
from typing import Any

from ci2lab.harness.types import ToolCall, ToolResult

_PDF_PATH_RE = re.compile(r"(?P<path>[^\s`\"']+\.pdf)\b", re.IGNORECASE)


def summarize_args(args: dict) -> str:
    if "command" in args:
        cmd = args["command"]
        return cmd[:60] + ("..." if len(cmd) > 60 else "")
    if "url" in args:
        url = str(args["url"])
        return url[:60] + ("..." if len(url) > 60 else "")
    if "question" in args:
        q = str(args["question"])
        return q[:60] + ("..." if len(q) > 60 else "")
    if "path" in args:
        return str(args["path"])
    if "pattern" in args:
        return str(args["pattern"])
    if "todos" in args and isinstance(args["todos"], list):
        return f"{len(args['todos'])} items"
    return ""


def pdf_tool_retry_hint(user_prompt: str, *, selection_tool_mode: str) -> str | None:
    match = _PDF_PATH_RE.search(user_prompt)
    if not match:
        return None

    pdf_path = match.group("path")
    if selection_tool_mode == "fenced":
        return (
            "La petición del usuario requiere leer un PDF del directorio de trabajo. "
            "No digas que no puedes acceder al archivo: tienes herramientas locales. "
            "Llama ahora a la herramienta `read_file` con este bloque exacto, espera el "
            "resultado y después responde a la tarea del usuario:\n"
            "```read_file\n"
            f"{pdf_path}\n"
            "```"
        )

    return (
        "La petición del usuario requiere leer un PDF del directorio de trabajo. "
        "No digas que no puedes acceder al archivo: tienes herramientas locales. "
        f"Invoca ahora la herramienta read_file con path={pdf_path!r}, espera el "
        "resultado y después responde a la tarea del usuario."
    )


def is_pdf_read_tool_call(tool_name: str, args: dict[str, Any]) -> bool:
    if tool_name == "read_file":
        return str(args.get("path", "")).lower().endswith(".pdf")
    if tool_name == "grep":
        path = str(args.get("path", "")).lower()
        glob = str(args.get("glob", "")).lower()
        return path.endswith(".pdf") or ".pdf" in glob
    return False


def forced_pdf_read_tool_call(user_prompt: str) -> ToolCall | None:
    match = _PDF_PATH_RE.search(user_prompt)
    if not match:
        return None
    return ToolCall(
        name="read_file",
        arguments={"path": match.group("path")},
        call_id="auto_pdf_read",
    )


def web_fetch_failed_nudge(results: list[ToolResult]) -> str | None:
    """Return a redirect hint when web_fetch fails with an HTTP error.

    The model tends to construct URLs from memory (which are often wrong or
    blocked).  When that happens, nudge it to use web_search instead.
    """
    _HTTP_ERROR_CODES = {"400", "401", "403", "404", "429", "500", "502", "503"}
    for result in results:
        if result.tool_name != "web_fetch" or not result.is_error:
            continue
        if any(code in result.content for code in _HTTP_ERROR_CODES):
            return (
                f"web_fetch failed: {result.content}\n\n"
                "The URL was likely wrong or the site blocks direct access. "
                "Do NOT guess or retry a different URL. "
                "Instead, call web_search with a plain text query to find the "
                "correct URL, then optionally fetch that specific result."
            )
    return None


def pdf_tool_result_followup(
    results: list[ToolResult],
    original_user_prompt: str,
) -> str | None:
    pdf_outputs = [
        result.content
        for result in results
        if result.tool_name == "read_file"
        and not result.is_error
        and "[PDF page " in result.content
    ]
    if not pdf_outputs:
        return None
    content = "\n\n".join(pdf_outputs)
    return (
        "Contenido del PDF leído con la herramienta `read_file`:\n\n"
        f"{content}\n\n"
        "Ahora responde a la petición original usando exclusivamente ese contenido. "
        f"Petición original: {original_user_prompt}"
    )
