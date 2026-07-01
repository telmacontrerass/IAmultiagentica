"""OpenCode-style permissions: allow / ask / deny with patterns (EXPERIMENTAL)."""

from __future__ import annotations

import fnmatch
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from ci2lab.security.decisions import DecisionAction, SecurityDecision
from ci2lab.security.paths import is_within_workspace

PermissionValue = str  # allow | ask | deny

_READ_TOOLS = frozenset(
    {
        "read_file",
        "extract_visual_document",
        "inspect_file",
        "file_info",
        "tree",
        "grep",
        "glob",
        "ls",
    }
)
_EDIT_TOOLS = frozenset({"write_file", "edit_file"})
_BASH_TOOLS = frozenset({"bash", "shell"})

_TOOL_TO_OPENCODE: dict[str, str] = {}
for _t in _READ_TOOLS:
    _TOOL_TO_OPENCODE[_t] = "read"
for _t in _EDIT_TOOLS:
    _TOOL_TO_OPENCODE[_t] = "edit"
for _t in _BASH_TOOLS:
    _TOOL_TO_OPENCODE[_t] = "bash"

_TOOL_RULE_ALIASES: dict[str, list[str]] = {}
for _t in _READ_TOOLS:
    _TOOL_RULE_ALIASES[_t] = ["read", _t]
_TOOL_RULE_ALIASES["write_file"] = ["edit", "write", "write_file"]
_TOOL_RULE_ALIASES["edit_file"] = ["edit", "edit_file"]
for _t in _BASH_TOOLS:
    _TOOL_RULE_ALIASES[_t] = ["bash", "shell", _t]

_DEFAULT_EXPERIMENTAL_RULES: dict[str, Any] = {
    "*": "ask",
    "skill": "allow",
    "yard": "allow",
    "ask_user": "allow",
    "todo_write": "allow",
    "read": {
        "*": "allow",
        ".env": "deny",
        "*.env": "deny",
        "*.env.*": "deny",
        "**/.env": "deny",
        "**/.env.*": "deny",
    },
    "edit": "ask",
    "bash": {
        "*": "ask",
        "git *": "allow",
        "pytest *": "allow",
        "rm *": "deny",
        "del *": "deny",
        "rmdir *": "deny",
        "rd *": "deny",
        "erase *": "deny",
        "Remove-Item *": "deny",
        "git clean *": "deny",
        "git reset --hard*": "deny",
        "find * -delete*": "deny",
        "find * -exec rm*": "deny",
        "xargs rm *": "deny",
        "*| xargs rm*": "deny",
        "chmod -R *": "deny",
        "chown -R *": "deny",
        "sudo *": "deny",
        "dd *": "deny",
        "mkfs*": "deny",
        "mount *": "deny",
        "umount *": "deny",
        "truncate *": "deny",
        "shred *": "deny",
        "bash -c *": "deny",
        "sh -c *": "deny",
    },
    "external_directory": {
        "*": "deny",
    },
}


@dataclass
class OpenCodePermissionConfig:
    """permission rules from opencode.json (subset)."""

    rules: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def default_experimental(cls) -> OpenCodePermissionConfig:
        """Return a config seeded with the built-in experimental defaults."""
        return cls(rules=dict(_DEFAULT_EXPERIMENTAL_RULES))

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> OpenCodePermissionConfig:
        """Build a config by merging ``raw`` over the experimental defaults.

        Args:
            raw: Permission rules to overlay; falsy values fall back to the
                defaults.

        Returns:
            A new :class:`OpenCodePermissionConfig` with merged rules.
        """
        if not raw:
            return cls.default_experimental()
        merged = dict(_DEFAULT_EXPERIMENTAL_RULES)
        for key, value in raw.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = value
        return cls(rules=merged)


def parse_opencode_permissions(raw: Mapping[str, Any] | None) -> OpenCodePermissionConfig:
    """Parse a raw permission mapping into an :class:`OpenCodePermissionConfig`.

    Args:
        raw: Permission rules to parse; falsy values use the defaults.

    Returns:
        The parsed permission config.
    """
    return OpenCodePermissionConfig.from_mapping(raw)


def _normalize_permission(value: str) -> PermissionValue:
    """Normalize and validate a single permission action.

    Raises:
        ValueError: If ``value`` is not one of allow|ask|deny.
    """
    v = value.strip().lower()
    if v not in {"allow", "ask", "deny"}:
        raise ValueError(f"invalid permission: {value!r} (use allow|ask|deny)")
    return v


def _normalize_slashes(text: str) -> str:
    """Convert backslashes to forward slashes for stable pattern matching."""
    return text.replace("\\", "/")


def _path_subjects(path: str) -> list[str]:
    """Candidates for path matching (Unix and Windows normalized)."""
    norm = _normalize_slashes(path.strip())
    subjects = [norm]
    try:
        name = PurePosixPath(norm).name
        if name:
            subjects.append(name)
            subjects.append(f"**/{name}")
    except ValueError:
        pass
    return list(dict.fromkeys(subjects))


def _expand_home(pattern: str) -> str:
    """Expand a leading ``~`` or ``$HOME`` in a glob pattern to the home dir."""
    if pattern.startswith("~/") or pattern == "~":
        return str(Path.home()).replace("\\", "/") + pattern[1:]
    if pattern.startswith("$HOME/") or pattern == "$HOME":
        home = os.environ.get("HOME") or os.environ.get("USERPROFILE") or ""
        home = home.replace("\\", "/")
        return home + pattern[5:] if pattern.startswith("$HOME") else pattern
    return pattern


def _pattern_specificity(pattern: str) -> int:
    """Score a pattern's specificity (more literal chars means more specific)."""
    if pattern in ("*", "**"):
        return 0
    return len(pattern.replace("*", "").replace("?", ""))


def _pattern_matches(pattern: str, subject: str) -> bool:
    """Return whether ``subject`` matches ``pattern`` (case-insensitive glob)."""
    expanded = _expand_home(pattern)
    norm_subject = _normalize_slashes(subject)
    for candidate in (expanded, pattern):
        if fnmatch.fnmatchcase(norm_subject, candidate):
            return True
        if fnmatch.fnmatchcase(norm_subject.lower(), candidate.lower()):
            return True
    return False


def _match_best_rule(
    rules: dict[str, Any] | str,
    subject: str,
    *,
    rule_prefix: str = "",
) -> tuple[PermissionValue | None, str | None]:
    """Most specific rule wins; tie -> last in declaration order."""
    if not isinstance(rules, dict):
        return _normalize_permission(str(rules)), f"{rule_prefix}*"

    best_perm: PermissionValue | None = None
    best_pattern: str | None = None
    best_score = -1
    best_index = -1

    for index, (pattern, action) in enumerate(rules.items()):
        if not _pattern_matches(pattern, subject):
            continue
        score = _pattern_specificity(pattern)
        if score > best_score or (score == best_score and index > best_index):
            best_score = score
            best_index = index
            best_pattern = pattern
            best_perm = _normalize_permission(str(action))

    if best_perm is None:
        return None, None
    matched = f"{rule_prefix}{best_pattern}" if rule_prefix else str(best_pattern)
    return best_perm, matched


def _tool_rule_keys(tool_name: str) -> list[str]:
    """Return the ordered permission-rule keys to try for ``tool_name``."""
    if tool_name in _TOOL_RULE_ALIASES:
        return list(dict.fromkeys(_TOOL_RULE_ALIASES[tool_name]))
    oc = _TOOL_TO_OPENCODE.get(tool_name, tool_name)
    keys = [oc]
    if tool_name != oc:
        keys.append(tool_name)
    return list(dict.fromkeys(keys))


def _resolve_tool_permission(
    rule_map: dict[str, Any],
    tool_name: str,
    subject: str,
) -> tuple[PermissionValue | None, str | None]:
    """Resolve the effective permission for a tool against the rule map.

    Tries tool-specific keys first, then the wildcard ``*`` key.

    Returns:
        A ``(permission, matched_rule)`` tuple; both are None if no rule
        applies.
    """
    for key in _tool_rule_keys(tool_name):
        if key not in rule_map:
            continue
        perm, matched = _match_best_rule(rule_map[key], subject, rule_prefix=f"{key}:")
        if perm is not None:
            return perm, matched
    if "*" in rule_map:
        perm, matched = _match_best_rule(rule_map["*"], subject, rule_prefix="*:")
        return perm, matched
    return None, None


def _permission_to_decision(
    perm: PermissionValue | None,
    *,
    default: PermissionValue = "ask",
    context: str,
    matched_rule: str | None = None,
    external_directory: bool = False,
) -> SecurityDecision:
    """Map a resolved permission value to a :class:`SecurityDecision`.

    Args:
        perm: Resolved permission value, or None to use ``default``.
        default: Permission applied when ``perm`` is None.
        context: Short label describing the evaluation context.
        matched_rule: Identifier of the rule that produced ``perm``.
        external_directory: True if the target lies outside the workspace.

    Returns:
        The decision corresponding to allow/ask/deny.
    """
    effective = perm or default
    if effective == "deny":
        return SecurityDecision(
            action=DecisionAction.DENY,
            reason=f"permission_deny:{context}",
            outcome="blocked_by_permission",
            message=f"Error: permission denied by OpenCode policy ({context})",
            matched_rule=matched_rule,
            external_directory=external_directory,
        )
    if effective == "ask":
        return SecurityDecision(
            action=DecisionAction.CONFIRM,
            reason=f"permission_ask:{context}",
            matched_rule=matched_rule,
            external_directory=external_directory,
        )
    return SecurityDecision(
        action=DecisionAction.ALLOW,
        reason=f"permission_allow:{context}",
        matched_rule=matched_rule,
        external_directory=external_directory,
    )


def _bash_subject(command: str) -> str:
    """Collapse whitespace in a command to a single-spaced match subject."""
    return re.sub(r"\s+", " ", command.strip())


def _is_external_path(workspace: str, path: str) -> bool:
    """Return whether ``path`` resolves outside ``workspace``."""
    return not is_within_workspace(path, workspace)


def evaluate_opencode_tool(
    tool_name: str,
    args: dict[str, Any],
    *,
    workspace: str,
    rules: OpenCodePermissionConfig,
    auto_confirm: bool,
) -> SecurityDecision:
    """Evaluate OpenCode permissions for a tool call without CI2Lab hard-checks.

    EXPERIMENTAL / UNSAFE: does not apply workspace confinement or the secret
    policy; those are layered separately by the engine when applicable.

    Args:
        tool_name: Name of the tool being evaluated.
        args: Arguments passed to the tool.
        workspace: Path to the workspace root.
        rules: The permission rules to apply.
        auto_confirm: If True, ``ask`` decisions resolve to ``allow``.

    Returns:
        The :class:`SecurityDecision` produced by the permission rules.
    """
    rule_map = rules.rules
    path_tools = _READ_TOOLS | _EDIT_TOOLS

    if tool_name in path_tools:
        path = str(args.get("path", "."))
        if _is_external_path(workspace, path):
            ext_rules = rule_map.get("external_directory", {"*": "deny"})
            ext_perm, ext_matched = _match_best_rule(
                ext_rules if isinstance(ext_rules, dict) else {"*": ext_rules},
                _normalize_slashes(path),
                rule_prefix="external_directory:",
            )
            ext_decision = _permission_to_decision(
                ext_perm,
                context=f"external_directory:{path}",
                matched_rule=ext_matched,
                external_directory=True,
            )
            if ext_decision.action is not DecisionAction.ALLOW:
                if ext_decision.action is DecisionAction.CONFIRM and auto_confirm:
                    pass
                else:
                    return ext_decision

    if tool_name in _BASH_TOOLS:
        cmd = _bash_subject(str(args.get("command", "")))
        perm, matched = _resolve_tool_permission(rule_map, tool_name, cmd)
        decision = _permission_to_decision(perm, context=f"bash:{cmd[:60]}", matched_rule=matched)
        if decision.action is DecisionAction.CONFIRM and auto_confirm:
            return SecurityDecision(
                action=DecisionAction.ALLOW,
                reason="auto_confirm",
                matched_rule=matched,
            )
        return decision

    path = str(args.get("path", "."))
    subjects = _path_subjects(path)
    # Types come from the unpacking of `_resolve_tool_permission` above; these
    # are plain re-initialisations (annotating again would shadow that binding).
    perm = None
    matched = None
    subject = path
    for candidate in subjects:
        perm, matched = _resolve_tool_permission(rule_map, tool_name, candidate)
        if perm is not None:
            subject = candidate
            break
    if perm is None:
        perm, matched = _resolve_tool_permission(rule_map, tool_name, path)

    decision = _permission_to_decision(
        perm,
        context=f"{tool_name}:{subject[:60]}",
        matched_rule=matched,
        external_directory=_is_external_path(workspace, path),
    )
    if decision.action is DecisionAction.CONFIRM and auto_confirm:
        return SecurityDecision(
            action=DecisionAction.ALLOW,
            reason="auto_confirm",
            matched_rule=matched,
            external_directory=decision.external_directory,
        )
    return decision
