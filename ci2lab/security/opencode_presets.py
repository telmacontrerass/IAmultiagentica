"""Presets de permission OpenCode (EXPERIMENTAL, solo opencode_experimental)."""

from __future__ import annotations

from typing import Any

PRESET_NAMES = frozenset({
    "opencode_paranoid",
    "opencode_dev",
    "opencode_external_allowed",
})

_DEFAULT_PRESET = "opencode_paranoid"


class UnknownPermissionPresetError(ValueError):
    """Preset de permission OpenCode no reconocido."""


_PRESETS: dict[str, dict[str, Any]] = {
    "opencode_paranoid": {
        "*": "ask",
        "read": {
            "*": "allow",
            ".env": "deny",
            "*.env": "deny",
            "*.env.*": "deny",
            "**/.env": "deny",
            "**/.env.*": "deny",
        },
        "edit": "deny",
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
        },
        "external_directory": {"*": "deny"},
    },
    "opencode_dev": {
        "*": "ask",
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
        },
        "external_directory": {"*": "deny"},
    },
    "opencode_external_allowed": {
        "*": "ask",
        "read": {"*": "allow"},
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
        },
        "external_directory": {"*": "allow"},
    },
}


def normalize_permission_preset(name: str | None) -> str | None:
    if not name:
        return None
    key = name.strip().lower()
    if key not in PRESET_NAMES:
        valid = ", ".join(sorted(PRESET_NAMES))
        raise UnknownPermissionPresetError(
            f"Preset de permission desconocido: {name!r}. Valores validos: {valid}."
        )
    return key


def preset_permissions(name: str) -> dict[str, Any]:
    key = normalize_permission_preset(name)
    assert key is not None
    return dict(_PRESETS[key])


def list_permission_presets() -> list[str]:
    return sorted(PRESET_NAMES)
