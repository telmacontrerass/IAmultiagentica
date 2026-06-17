"""Generic, task-agnostic helpers for the agent loop (console + web nudges)."""

from __future__ import annotations

from ci2lab.harness.types import ToolResult

_HTTP_ERROR_CODES = {"400", "401", "403", "404", "429", "500", "502", "503"}


def summarize_args(args: dict) -> str:
    """Short one-line summary of a tool call's arguments for the console."""
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


def web_fetch_failed_nudge(results: list[ToolResult]) -> str | None:
    """Return a redirect hint when web_fetch fails with an HTTP error.

    The model tends to construct URLs from memory (which are often wrong or
    blocked). When that happens, nudge it to use web_search instead.
    """
    for result in results:
        if result.tool_name != "web_fetch" or not result.is_error:
            continue
        if any(code in result.content for code in _HTTP_ERROR_CODES):
            return (
                f"web_fetch failed: {result.content}\n\n"
                "The URL was likely wrong or the site blocks direct access. "
                "Do NOT guess or retry a different URL. "
                "Instead, call web_search with a plain-text query to find the "
                "correct URL, then optionally fetch that specific result."
            )
    return None
