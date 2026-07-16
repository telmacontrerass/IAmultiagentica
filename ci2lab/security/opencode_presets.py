"""OpenCode permission presets (EXPERIMENTAL, opencode_experimental only)."""

from __future__ import annotations

from typing import Any

from ci2lab.security.opencode_defaults import build_default_permissions

PRESET_NAMES = frozenset(
    {
        "opencode_paranoid",
        "opencode_dev",
        "opencode_external_allowed",
    }
)

_DEFAULT_PRESET = "opencode_paranoid"


class UnknownPermissionPresetError(ValueError):
    """Raised when an OpenCode permission preset name is not recognized."""


_PRESETS: dict[str, dict[str, Any]] = {
    "opencode_paranoid": build_default_permissions(edit="deny", external_directory="deny"),
    "opencode_dev": build_default_permissions(edit="ask", external_directory="deny"),
    "opencode_external_allowed": build_default_permissions(
        edit="ask",
        external_directory="allow",
        protect_sensitive_files=False,
    ),
}


def normalize_permission_preset(name: str | None) -> str | None:
    """Normalize a permission preset name to its canonical key.

    Args:
        name: User-provided preset name; may be None or empty.

    Returns:
        The canonical preset key, or None when ``name`` is falsy.

    Raises:
        UnknownPermissionPresetError: If ``name`` is a non-empty unknown
            preset.
    """
    if not name:
        return None
    key = name.strip().lower()
    if key not in PRESET_NAMES:
        valid = ", ".join(sorted(PRESET_NAMES))
        raise UnknownPermissionPresetError(
            f"Unknown permission preset: {name!r}. Valid values: {valid}."
        )
    return key


def preset_permissions(name: str) -> dict[str, Any]:
    """Return a copy of the permission rules for a named preset.

    Args:
        name: Preset name (validated via :func:`normalize_permission_preset`).

    Returns:
        A shallow copy of the preset's permission-rule mapping.

    Raises:
        UnknownPermissionPresetError: If ``name`` is not a known preset.
    """
    key = normalize_permission_preset(name)
    assert key is not None
    return dict(_PRESETS[key])


def list_permission_presets() -> list[str]:
    """Return the available permission preset names, sorted alphabetically."""
    return sorted(PRESET_NAMES)
