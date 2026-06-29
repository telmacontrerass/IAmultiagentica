"""OpenAI function schemas for integration tools.

Defines :data:`INTEGRATIONS_SCHEMAS`, the schemas for tools that reach outside
the local file system or invoke auxiliary services (web search/fetch, git,
skills, image analysis, MCP calls). These are aggregated into the full tool set
by :mod:`ci2lab.harness.tools.schemas_parts.builtins`.
"""

from __future__ import annotations

from typing import Any

#: OpenAI-compatible function schemas for integration/service tools.
INTEGRATIONS_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web for up-to-date information using a plain text query. "
                "Use when you need current docs, news, or any information without knowing the URL. "
                "Returns titles, URLs, and snippets from DuckDuckGo."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Number of results to return (1-10, default 5)",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": (
                "Fetch a specific public http(s) URL and return its text (HTML is stripped). "
                "Only use when you already have a confirmed URL. "
                "If you do not have a URL, use web_search first. "
                "For news or sports results, use max_chars=8000 to keep the response concise."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "max_chars": {
                        "type": "integer",
                        "description": "Max characters to return (default 12000 for web pages; up to 80000 for docs)",
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Show short git status for the workspace or a path inside it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path relative to workspace (default .)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "Show git diff for the workspace or a specific file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "staged": {
                        "type": "boolean",
                        "description": "If true, show staged changes only",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "skill",
            "description": (
                "Load a workspace skill workflow by name. Returns instructions to follow "
                "using the listed tools. Use when a skill in the catalog matches the task."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "Skill name from the Skills catalog",
                    },
                    "args": {
                        "type": "string",
                        "description": "Optional free-text arguments for the skill",
                    },
                },
                "required": ["skill_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_image",
            "description": (
                "Analyze a local image file and return a detailed text description. "
                "Use when the task involves understanding, describing, or extracting "
                "information from an image (screenshots, diagrams, photos, charts). "
                "Requires a vision-capable model to be available — either the active "
                "model or the configured vision_model fallback."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "Absolute or workspace-relative path to the image file "
                            "(JPEG, PNG, GIF, WEBP, BMP supported)"
                        ),
                    },
                    "model": {
                        "type": "string",
                        "description": (
                            "Optional: Ollama vision model tag to use for this call "
                            "(e.g. 'llava', 'qwen3-vl'). Overrides vision_model in settings."
                        ),
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extract_visual_document",
            "description": (
                "Extract text and formulas from a local image or scanned/handwritten PDF. "
                "This tool is extraction-only and always uses qwen2.5vl:7b under the hood. "
                "Use with the review_handwritten_exercise skill when the user asks to "
                "transcribe handwritten work and check calculations step by step."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "Absolute or workspace-relative path to the source file "
                            "(PDF, JPEG, PNG, GIF, WEBP, BMP, TIFF)"
                        ),
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mcp_call",
            "description": (
                "Call a tool on a connected MCP server by server name and tool name. "
                "Prefer dedicated mcp__* tools when listed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "server": {"type": "string"},
                    "tool": {"type": "string"},
                    "arguments": {
                        "type": "object",
                        "description": "Tool arguments object",
                    },
                },
                "required": ["server", "tool"],
            },
        },
    },
]
