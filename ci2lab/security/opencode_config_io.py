"""Import/export and validation of OpenCode-style configs (EXPERIMENTAL)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ci2lab.security.opencode_permissions import (
    OpenCodePermissionConfig,
    parse_opencode_permissions,
)

_VALID_ACTIONS = frozenset({"allow", "ask", "deny"})

_SUPPORTED_OPENCODE_KEYS = frozenset(
    {
        "*",
        "read",
        "edit",
        "write",
        "write_file",
        "edit_file",
        "bash",
        "shell",
        "grep",
        "glob",
        "list",
        "external_directory",
    }
)

_EXTERNAL_ALLOW_WARNING = (
    "UNSAFE: external_directory=allow permits access outside the workspace in opencode_experimental"
)


@dataclass(frozen=True)
class OpenCodeConfigBundle:
    """Result of loading and normalizing an OpenCode/CI2Lab config.

    Attributes:
        config_source: Origin of the config (file path, preset or inline).
        raw_config: The raw parsed JSON object.
        permission: The extracted permission mapping.
        normalized_permission: The permission mapping after normalization.
        unsupported_tools: OpenCode tool keys not mapped in CI2Lab.
        warnings: Advisory warnings collected during loading.
    """

    config_source: str
    raw_config: dict[str, Any]
    permission: dict[str, Any]
    normalized_permission: dict[str, Any]
    unsupported_tools: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_permission_config(self) -> OpenCodePermissionConfig:
        """Build an :class:`OpenCodePermissionConfig` from this bundle."""
        return parse_opencode_permissions(self.normalized_permission)


def load_opencode_config(path: str | Path) -> dict[str, Any]:
    """Load a JSON config object from disk.

    Args:
        path: Path to the JSON config file.

    Returns:
        The parsed config as a dict.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file is not valid JSON or not a JSON object.
    """
    raw_path = Path(path).expanduser().resolve()
    if not raw_path.is_file():
        raise FileNotFoundError(f"Configuration file does not exist: {raw_path}")
    try:
        data = json.loads(raw_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {raw_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"The configuration must be a JSON object: {raw_path}")
    return data


def extract_opencode_permission(config: dict[str, Any]) -> dict[str, Any]:
    """Extract the permission mapping from a config object.

    Precedence: ``security.permission`` > root ``permission`` > a config that
    already looks like a permission map.

    Args:
        config: Parsed config object.

    Returns:
        A copy of the extracted permission mapping.

    Raises:
        ValueError: If ``config`` is not a dict or no permission is found.
    """
    if not isinstance(config, dict):
        raise ValueError("config must be a JSON object.")

    security = config.get("security")
    if isinstance(security, dict):
        sec_perm = security.get("permission")
        if isinstance(sec_perm, dict):
            return dict(sec_perm)

    root_perm = config.get("permission")
    if isinstance(root_perm, dict):
        return dict(root_perm)

    if _looks_like_permission_map(config):
        return dict(config)

    raise ValueError("permission not found: use root key 'permission' or 'security.permission'.")


def _looks_like_permission_map(data: dict[str, Any]) -> bool:
    """Return whether ``data`` resembles a permission map by its top-level keys."""
    markers = {"read", "edit", "bash", "external_directory", "*"}
    return any(key in data for key in markers)


def _normalize_action(value: str) -> str:
    """Normalize and validate a permission action string.

    Raises:
        ValueError: If ``value`` is not one of allow|ask|deny.
    """
    action = value.strip().lower()
    if action not in _VALID_ACTIONS:
        raise ValueError(f"invalid permission action: {value!r} (use allow|ask|deny)")
    return action


def normalize_opencode_permission(permission: dict[str, Any]) -> dict[str, Any]:
    """Normalize allow/ask/deny values recursively across a permission map.

    Args:
        permission: Permission mapping to normalize.

    Returns:
        A new mapping with normalized action strings.

    Raises:
        ValueError: If ``permission`` is not a dict or holds an invalid value.
    """
    if not isinstance(permission, dict):
        raise ValueError("permission must be a JSON object.")
    return _normalize_permission_node(permission)


def _normalize_permission_node(node: dict[str, Any]) -> dict[str, Any]:
    """Recursively normalize action strings within a permission subtree."""
    normalized: dict[str, Any] = {}
    for key, value in node.items():
        if isinstance(value, dict):
            normalized[key] = _normalize_permission_node(value)
        elif isinstance(value, str):
            normalized[key] = _normalize_action(value)
        else:
            raise ValueError(f"invalid value in permission[{key!r}]: must be a string or object")
    return normalized


def validate_opencode_permission(permission: dict[str, Any]) -> None:
    """Validate a permission map's structure and action values.

    Args:
        permission: Permission mapping to validate.

    Raises:
        ValueError: If the structure or any action value is invalid.
    """
    if not isinstance(permission, dict):
        raise ValueError("permission must be a JSON object.")
    _validate_permission_node(permission, path="permission")


def _validate_permission_node(node: dict[str, Any], *, path: str) -> None:
    """Recursively validate a permission subtree, reporting the failing path."""
    for key, value in node.items():
        current = f"{path}.{key}"
        if isinstance(value, dict):
            _validate_permission_node(value, path=current)
        elif isinstance(value, str):
            _normalize_action(value)
        else:
            raise ValueError(f"{current}: value must be a string (allow|ask|deny) or object")


def detect_unsupported_opencode_tools(permission: dict[str, Any]) -> list[str]:
    """List permission keys not mapped to CI2Lab tools (warning, not error).

    Args:
        permission: Permission mapping to inspect.

    Returns:
        A sorted list of unsupported top-level keys.
    """
    unsupported: list[str] = []
    for key in permission:
        if key not in _SUPPORTED_OPENCODE_KEYS:
            unsupported.append(str(key))
    return sorted(unsupported)


def collect_permission_warnings(permission: dict[str, Any]) -> list[str]:
    """Collect advisory warnings for a permission map.

    Args:
        permission: Permission mapping to inspect.

    Returns:
        A list of warnings (unsupported tools, unsafe external access).
    """
    warnings: list[str] = []
    unsupported = detect_unsupported_opencode_tools(permission)
    if unsupported:
        warnings.append(
            "OpenCode tools not supported in CI2Lab (ignored): " + ", ".join(unsupported)
        )
    if _external_directory_allows(permission):
        warnings.append(_EXTERNAL_ALLOW_WARNING)
    return warnings


def _external_directory_allows(permission: dict[str, Any]) -> bool:
    """Return whether the permission map allows external-directory access."""
    ext = permission.get("external_directory")
    if isinstance(ext, str):
        return ext.strip().lower() == "allow"
    if isinstance(ext, dict):
        for pattern, action in ext.items():
            if str(action).strip().lower() == "allow":
                if pattern in ("*", "**"):
                    return True
        best = ext.get("*")
        return isinstance(best, str) and best.strip().lower() == "allow"
    return False


def load_opencode_config_bundle(
    path: str | Path,
    *,
    config_source: str | None = None,
) -> OpenCodeConfigBundle:
    """Load, extract, normalize and validate a permission config from a file.

    Args:
        path: Path to the JSON config file.
        config_source: Optional override for the bundle's ``config_source``.

    Returns:
        A fully populated :class:`OpenCodeConfigBundle`.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file or its permission map is invalid.
    """
    raw_path = Path(path).expanduser().resolve()
    raw = load_opencode_config(raw_path)
    permission = extract_opencode_permission(raw)
    validate_opencode_permission(permission)
    normalized = normalize_opencode_permission(permission)
    unsupported = detect_unsupported_opencode_tools(permission)
    warnings = collect_permission_warnings(permission)
    return OpenCodeConfigBundle(
        config_source=config_source or str(raw_path),
        raw_config=raw,
        permission=permission,
        normalized_permission=normalized,
        unsupported_tools=unsupported,
        warnings=warnings,
    )


def bundle_from_permission(
    permission: dict[str, Any],
    *,
    config_source: str = "<inline>",
) -> OpenCodeConfigBundle:
    """Build a config bundle from an in-memory permission map.

    Args:
        permission: Permission mapping to wrap.
        config_source: Label identifying the origin of the permission map.

    Returns:
        A populated :class:`OpenCodeConfigBundle`.

    Raises:
        ValueError: If the permission map is invalid.
    """
    validate_opencode_permission(permission)
    normalized = normalize_opencode_permission(permission)
    unsupported = detect_unsupported_opencode_tools(permission)
    warnings = collect_permission_warnings(permission)
    return OpenCodeConfigBundle(
        config_source=config_source,
        raw_config={"permission": permission},
        permission=dict(permission),
        normalized_permission=normalized,
        unsupported_tools=unsupported,
        warnings=warnings,
    )


def bundle_from_preset(preset_name: str) -> OpenCodeConfigBundle:
    """Build a config bundle from a named permission preset.

    Args:
        preset_name: Name of the preset to load.

    Returns:
        A populated :class:`OpenCodeConfigBundle` for the preset.

    Raises:
        UnknownPermissionPresetError: If the preset name is unknown.
    """
    from ci2lab.security.opencode_presets import preset_permissions

    permission = preset_permissions(preset_name)
    bundle = bundle_from_permission(permission, config_source=f"preset:{preset_name}")
    return bundle


def export_opencode_format(permission: dict[str, Any]) -> dict[str, Any]:
    """Render a permission map in OpenCode's root-level ``permission`` format.

    Args:
        permission: Permission mapping to export.

    Returns:
        A dict with a single normalized ``permission`` key.
    """
    normalized = normalize_opencode_permission(permission)
    return {"permission": normalized}


def export_ci2lab_format(
    permission: dict[str, Any],
    *,
    permission_preset: str | None = None,
) -> dict[str, Any]:
    """Render a permission map in CI2Lab's ``security`` config format.

    Args:
        permission: Permission mapping to export.
        permission_preset: Optional preset name to record in the output.

    Returns:
        A dict with a ``security`` section for the opencode_experimental
        engine.
    """
    normalized = normalize_opencode_permission(permission)
    security: dict[str, Any] = {
        "engine": "opencode_experimental",
        "permission": normalized,
    }
    if permission_preset:
        security["permission_preset"] = permission_preset
    return {"security": security}


def export_warnings_for_permission(permission: dict[str, Any]) -> list[str]:
    """Return advisory warnings for a permission map (export convenience)."""
    return collect_permission_warnings(permission)


def write_json_output(
    payload: dict[str, Any],
    *,
    output: Path | None,
    workspace: Path | None = None,
) -> None:
    """Write a JSON payload to stdout or a file.

    Args:
        payload: JSON-serializable mapping to write.
        output: Destination path, or None to print to stdout. A relative path
            is resolved against ``workspace`` when provided.
        workspace: Base directory for resolving a relative ``output`` path.
    """
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if output is None:
        print(text, end="")
        return
    target = Path(output).expanduser()
    if not target.is_absolute() and workspace is not None:
        target = workspace.resolve() / target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
