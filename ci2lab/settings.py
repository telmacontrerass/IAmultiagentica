"""
Tool permissions via hierarchical settings.json.

File format:
    {
      "allow": { "<tool>": ["<pattern>", ...] },
      "deny":  { "<tool>": ["<pattern>", ...] }
    }

Semantics:
  - deny is evaluated first and always wins (they are not complementary).
  - If a tool does not appear in allow → allowed by default.
  - If a tool appears in allow → the subject must match at least one pattern.
  - allow + deny on the same tool → deny wins if there is a match.

File hierarchy (load order):
  1. ~/.ci2lab/settings.json  (global / user)
  2. .ci2lab/settings.json    (project; applied on top of global)

Merge rules:
  - deny:  accumulation. The project cannot remove denies from the global level.
  - allow: the project overrides per tool (can broaden or restrict).
"""

from __future__ import annotations

import fnmatch
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SETTINGS_FILENAME = "settings.json"
_VALID_TOP_KEYS = frozenset({"allow", "deny", "vision_model", "vision_enabled"})


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class ToolSettings:
    """allow/deny rules and vision settings already merged from all active levels."""

    allow: dict[str, list[str]] = field(default_factory=dict)
    deny: dict[str, list[str]] = field(default_factory=dict)

    vision_model: str | None = None
    """Ollama tag of the fallback vision model (None = not configured)."""

    vision_enabled: bool | None = None
    """Whether vision features are enabled (None = not configured, defaults to True)."""

    @classmethod
    def empty(cls) -> ToolSettings:
        """Return a ToolSettings with no allow/deny rules and unset vision config."""
        return cls()


# ---------------------------------------------------------------------------
# Search paths
# ---------------------------------------------------------------------------


def _settings_paths(cwd: str) -> list[Path]:
    """
    Return the paths to look for settings.json, from least to most
    specific.  The last layer (project) has higher precedence in allow.
    """
    return [
        Path.home() / ".ci2lab" / _SETTINGS_FILENAME,
        Path(cwd).resolve() / ".ci2lab" / _SETTINGS_FILENAME,
    ]


# ---------------------------------------------------------------------------
# Reading and parsing a file
# ---------------------------------------------------------------------------


def _load_raw(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        # Accept UTF-8 files both with and without BOM. Windows PowerShell's
        # `Set-Content -Encoding UTF8` may emit a BOM.
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        logger.warning("settings.json: could not read %s: %s", path, exc)
        return None
    except json.JSONDecodeError as exc:
        logger.warning("settings.json: invalid JSON in %s: %s", path, exc)
        return None
    if not isinstance(data, dict):
        logger.warning("settings.json: %s is not a JSON object; ignored.", path)
        return None
    return data


def _parse_tool_patterns(
    raw: Any,
    *,
    context: str,
) -> dict[str, list[str]]:
    """
    Parse an allow or deny block.

    Accepts:
      { "bash": ["rm *", "del *"], "read_file": "*.env" }

    Ignores invalid entries with a warning instead of raising exceptions.
    """
    if not isinstance(raw, dict):
        logger.warning("settings.json (%s): must be {tool: [patterns]}; ignored.", context)
        return {}
    result: dict[str, list[str]] = {}
    for tool, patterns in raw.items():
        tool = str(tool)
        if isinstance(patterns, str):
            patterns = [patterns]
        if not isinstance(patterns, list):
            logger.warning(
                "settings.json (%s.%s): patterns must be a list or string; ignored.",
                context,
                tool,
            )
            continue
        cleaned = [str(p).strip() for p in patterns if str(p).strip()]
        if cleaned:
            result[tool] = cleaned
    return result


def _parse_single_file(data: dict[str, Any], *, source: str) -> ToolSettings:
    unknown = set(data.keys()) - _VALID_TOP_KEYS
    if unknown:
        logger.warning("settings.json (%s): unknown keys ignored: %s", source, unknown)
    allow = _parse_tool_patterns(data.get("allow", {}), context=f"{source}.allow")
    deny = _parse_tool_patterns(data.get("deny", {}), context=f"{source}.deny")
    vision_model = str(data["vision_model"]) if "vision_model" in data else None
    vision_enabled = bool(data["vision_enabled"]) if "vision_enabled" in data else None
    return ToolSettings(
        allow=allow,
        deny=deny,
        vision_model=vision_model,
        vision_enabled=vision_enabled,
    )


# ---------------------------------------------------------------------------
# Layer merging
# ---------------------------------------------------------------------------


def _merge(global_s: ToolSettings, project_s: ToolSettings) -> ToolSettings:
    """
    Merge the global layer and the project layer:

    deny  → union. The global patterns CANNOT be removed by the project.
            The project can only add more restrictions.
    allow → the project overrides per tool (can broaden or change).
            If a tool does not appear in the project, the global is kept.
    """
    # deny: accumulate without duplicates, preserving order
    merged_deny: dict[str, list[str]] = {}
    all_deny_tools = set(global_s.deny) | set(project_s.deny)
    for tool in all_deny_tools:
        seen: list[str] = []
        for p in global_s.deny.get(tool, []) + project_s.deny.get(tool, []):
            if p not in seen:
                seen.append(p)
        merged_deny[tool] = seen

    # allow: project wins per tool; if the project does not define a tool,
    # the global value is kept
    merged_allow: dict[str, list[str]] = {**global_s.allow, **project_s.allow}

    # vision settings: project wins when set; otherwise fall back to global
    merged_vision_model = (
        project_s.vision_model if project_s.vision_model is not None else global_s.vision_model
    )
    merged_vision_enabled = (
        project_s.vision_enabled
        if project_s.vision_enabled is not None
        else global_s.vision_enabled
    )

    return ToolSettings(
        allow=merged_allow,
        deny=merged_deny,
        vision_model=merged_vision_model,
        vision_enabled=merged_vision_enabled,
    )


# ---------------------------------------------------------------------------
# Public loading
# ---------------------------------------------------------------------------


def load_settings(cwd: str) -> ToolSettings:
    """
    Load and merge global-level and project-level settings.json.

    Never raises exceptions; read or parse errors are recorded with
    logging.warning and silently ignored.
    """
    layers: list[ToolSettings] = []
    for path in _settings_paths(cwd):
        raw = _load_raw(path)
        if raw is not None:
            layers.append(_parse_single_file(raw, source=str(path)))

    if not layers:
        return ToolSettings.empty()
    if len(layers) == 1:
        return layers[0]
    return _merge(layers[0], layers[1])


# ---------------------------------------------------------------------------
# Evaluating a specific call
# ---------------------------------------------------------------------------


def subject_for_tool(tool_name: str, args: dict[str, Any]) -> str:
    """
    Extract the relevant 'subject' of a call to compare it against patterns.

    | Tool        | Subject                        |
    |-------------|--------------------------------|
    | bash        | the full command               |
    | web_fetch   | the URL                        |
    | *_file / ls / glob / grep / tree / inspect_file | the path |
    | rest        | "*" (always matches "*")       |
    """
    if tool_name == "bash":
        return str(args.get("command", ""))
    if tool_name == "web_fetch":
        return str(args.get("url", ""))
    if tool_name in {"fill_docx_template", "write_pptx"}:
        # The subject is the output path (the file that will be written).
        # Other input paths are validated by workspace containment in previews.
        return str(args.get("output_path") or args.get("output") or "*")
    if "path" in args:
        return str(args["path"])
    if "pattern" in args:
        return str(args["pattern"])
    return "*"


def _normalize_path(s: str) -> str:
    """Normalize separators for cross-platform comparison."""
    return s.replace("\\", "/")


def _pattern_matches(pattern: str, subject: str) -> bool:
    """
    Compare a glob pattern against the subject.

    Strategies (in order):
    1. Direct fnmatch (case-insensitive on Windows).
    2. Prefix match for bash commands with spaces (e.g. "rm *" covers "rm -rf .").
    3. For patterns with "**": PurePosixPath.full_match() (Python 3.13+).
       - "**" can represent zero or more directory segments.
       - Respects concrete prefixes: ".ci2lab/output/**/*.docx" does NOT match
         "other/malicious.docx".
       - Fallback for Python < 3.13: bare-filename only when the pattern
         starts with "**/" without a concrete prefix.
    4. For patterns without "**": match against the bare filename
       (e.g. "*.pdf" matches "docs/report.pdf").
    """
    norm_s = _normalize_path(subject)
    norm_p = _normalize_path(pattern)

    # direct match (case-insensitive on Windows via lower())
    if fnmatch.fnmatchcase(norm_s, norm_p) or fnmatch.fnmatchcase(norm_s.lower(), norm_p.lower()):
        return True

    # for bash: try a prefix match (rm * must cover "rm -rf .")
    if " " in norm_p and norm_s.startswith(norm_p.split("*")[0]):
        return True

    # for patterns with **: use PurePosixPath.full_match() (Python 3.13+).
    # Path.match() dropped support for ** in Python 3.13; full_match() is the
    # official replacement and correctly handles zero segments and concrete prefixes.
    if "**" in norm_p:
        from pathlib import PurePosixPath

        if "/**/" in norm_p:
            zero_segment_pattern = norm_p.replace("/**/", "/")
            if fnmatch.fnmatchcase(norm_s, zero_segment_pattern) or fnmatch.fnmatchcase(
                norm_s.lower(), zero_segment_pattern.lower()
            ):
                return True

        try:
            # ``PurePath.full_match`` exists on Python 3.13+; on 3.11/3.12 the
            # AttributeError below triggers the manual fallback.
            if PurePosixPath(norm_s).full_match(norm_p):  # type: ignore[attr-defined]
                return True
            # case-insensitive (Windows)
            if PurePosixPath(norm_s.lower()).full_match(norm_p.lower()):  # type: ignore[attr-defined]
                return True
        except AttributeError:
            # Python < 3.13: full_match unavailable; manual fallback.
            # Only apply bare-filename when the pattern starts with "**/"
            # (without a concrete prefix) so we don't ignore the prefix by mistake.
            if norm_p.startswith("**/"):
                suffix = norm_p[3:]
                if suffix:
                    bare = norm_s.rsplit("/", 1)[-1] if "/" in norm_s else norm_s
                    if fnmatch.fnmatchcase(bare, suffix) or fnmatch.fnmatchcase(
                        bare.lower(), suffix.lower()
                    ):
                        return True

    # match only against the filename (last segment)
    # for patterns without ** used against paths with a directory (e.g. "*.pdf" vs "docs/x.pdf")
    filename = norm_s.rsplit("/", 1)[-1]
    if filename and filename != norm_s:
        if fnmatch.fnmatchcase(filename, norm_p) or fnmatch.fnmatchcase(
            filename.lower(), norm_p.lower()
        ):
            return True

    return False


def _first_match(patterns: list[str], subject: str) -> str | None:
    """Return the first pattern that matches, or None."""
    for p in patterns:
        if _pattern_matches(p, subject):
            return p
    return None


def check_tool_allowed(
    settings: ToolSettings,
    tool_name: str,
    args: dict[str, Any],
) -> tuple[bool, str]:
    """
    Evaluate whether a tool call is allowed according to settings.json rules.

    Returns (allowed: bool, reason: str).

    Algorithm:
      1. Extract the subject (path, command, URL, or "*").
      2. Look in deny[tool_name]: if there is a match → blocked (deny wins).
      3. If allow[tool_name] exists: the subject must match at least one pattern.
      4. If allow[tool_name] does not exist: allowed by default.
    """
    subject = subject_for_tool(tool_name, args)

    # 1. Deny: evaluated first, always wins
    deny_patterns = settings.deny.get(tool_name, [])
    matched_deny = _first_match(deny_patterns, subject)
    if matched_deny:
        return (
            False,
            f"blocked by settings.json deny[{tool_name!r}] pattern={matched_deny!r}",
        )

    # 2. Allow: if there is a list and the subject does not match → blocked
    allow_patterns = settings.allow.get(tool_name)
    if allow_patterns is not None:
        matched_allow = _first_match(allow_patterns, subject)
        if matched_allow is None:
            return (
                False,
                f"blocked by settings.json allow[{tool_name!r}]: no pattern matches {subject!r}",
            )

    # 3. Allowed
    return True, "settings:allowed"
