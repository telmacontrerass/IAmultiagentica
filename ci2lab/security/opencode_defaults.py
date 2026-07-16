"""Shared builders for the built-in OpenCode permission rules."""

from __future__ import annotations

from typing import Any

_SENSITIVE_READ_DENIES = {
    ".env": "deny",
    "*.env": "deny",
    "*.env.*": "deny",
    "**/.env": "deny",
    "**/.env.*": "deny",
}

_SAFE_BASH_RULES = {
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
}


def build_default_permissions(
    *,
    edit: str,
    external_directory: str,
    protect_sensitive_files: bool = True,
    allow_internal_tools: bool = False,
) -> dict[str, Any]:
    """Build an independent permission mapping for a built-in configuration."""
    read_rules = {"*": "allow"}
    if protect_sensitive_files:
        read_rules.update(_SENSITIVE_READ_DENIES)

    rules: dict[str, Any] = {
        "*": "ask",
        "read": read_rules,
        "edit": edit,
        "bash": dict(_SAFE_BASH_RULES),
        "external_directory": {"*": external_directory},
    }
    if allow_internal_tools:
        rules.update(
            {
                "skill": "allow",
                "yard": "allow",
                "ask_user": "allow",
                "todo_write": "allow",
            }
        )
    return rules
