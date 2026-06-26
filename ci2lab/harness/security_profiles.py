"""Configurable security profiles (without relaxing base guarantees)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ci2lab.security.opencode_permissions import (
    OpenCodePermissionConfig,
    parse_opencode_permissions,
)

SECURITY_PROFILE_BLOCKED_OUTCOME = "blocked_by_security_profile"

VALID_PROFILES = frozenset({"strict", "standard", "dev", "audit"})
DEFAULT_PROFILE = "standard"

# Tools blocked per profile (hardening only; never relaxes workspace/secrets).
_PROFILE_BLOCKED_TOOLS: dict[str, frozenset[str]] = {
    "strict": frozenset({"write_file", "edit_file", "bash"}),
    "standard": frozenset(),
    "dev": frozenset(),
    "audit": frozenset({"write_file", "edit_file", "bash"}),
}

_PROFILE_LIMIT_DEFAULTS: dict[str, tuple[int, int]] = {
    "strict": (60, 10_000),
    "standard": (60, 10_000),
    "dev": (120, 20_000),
    "audit": (60, 10_000),
}


@dataclass(frozen=True)
class SecurityLimits:
    """Resolved runtime limits for a security profile.

    Attributes:
        bash_timeout_seconds: Maximum wall-clock time allowed for a bash tool
            call, in seconds.
        max_tool_output_chars: Maximum number of characters retained from a
            tool's output before truncation.
    """

    bash_timeout_seconds: int
    max_tool_output_chars: int


@dataclass(frozen=True)
class SecurityConfig:
    """Parsed security configuration for a run.

    Attributes:
        profile: Active security profile name (one of ``VALID_PROFILES``).
        engine: Security engine identifier driving permission evaluation.
        bash_timeout_seconds: Optional override for the bash timeout; when
            ``None`` the profile default is used.
        max_tool_output_chars: Optional override for the tool-output cap; when
            ``None`` the profile default is used.
        permission: OpenCode-style permission mapping declared under
            ``security.permission``.
        permission_preset: Optional OpenCode preset name.
    """

    profile: str = DEFAULT_PROFILE
    engine: str = "claude_experimental"
    bash_timeout_seconds: int | None = None
    max_tool_output_chars: int | None = None
    permission: dict[str, Any] = field(default_factory=dict)
    permission_preset: str | None = None
    """OpenCode preset (opencode_experimental / claude_experimental)."""

    def resolved_limits(self) -> SecurityLimits:
        """Resolve effective limits, applying profile defaults where unset.

        Returns:
            A :class:`SecurityLimits` with explicit overrides taking precedence
            over the profile's default timeout and output cap.
        """
        default_timeout, default_output = _PROFILE_LIMIT_DEFAULTS[self.profile]
        return SecurityLimits(
            bash_timeout_seconds=(
                self.bash_timeout_seconds
                if self.bash_timeout_seconds is not None
                else default_timeout
            ),
            max_tool_output_chars=(
                self.max_tool_output_chars
                if self.max_tool_output_chars is not None
                else default_output
            ),
        )


class UnknownSecurityProfileError(ValueError):
    """Unrecognized security profile."""


def validate_profile(profile: str) -> str:
    """Normalize and validate a security profile name.

    Args:
        profile: Raw profile name (case and surrounding whitespace insensitive).

    Returns:
        The normalized (stripped, lower-cased) profile name.

    Raises:
        UnknownSecurityProfileError: If the name is not in ``VALID_PROFILES``.
    """
    normalized = profile.strip().lower()
    if normalized not in VALID_PROFILES:
        names = ", ".join(sorted(VALID_PROFILES))
        raise UnknownSecurityProfileError(
            f"Unknown security profile: {profile!r}. Valid values: {names}."
        )
    return normalized


def parse_security_config(raw: Mapping[str, Any] | None) -> SecurityConfig:
    """Build a :class:`SecurityConfig` from a raw mapping.

    Args:
        raw: Parsed ``security`` section from configuration, or ``None``.

    Returns:
        A :class:`SecurityConfig`; the default config when ``raw`` is falsy.

    Raises:
        ValueError: If ``raw`` or any nested section (``permission``,
            ``limits``) is not an object of the expected type.
        UnknownSecurityProfileError: If the configured profile is invalid.
    """
    if not raw:
        return SecurityConfig()
    if not isinstance(raw, dict):
        raise ValueError("security must be a JSON/YAML object.")

    profile = validate_profile(str(raw.get("profile", DEFAULT_PROFILE)))

    from ci2lab.security.engine import DEFAULT_SECURITY_ENGINE, normalize_security_engine

    engine = normalize_security_engine(str(raw.get("engine", DEFAULT_SECURITY_ENGINE)))

    permission_raw = raw.get("permission")
    permission: dict[str, Any] = {}
    if permission_raw is not None:
        if not isinstance(permission_raw, dict):
            raise ValueError("security.permission must be an object.")
        permission = dict(permission_raw)

    preset_raw = raw.get("permission_preset")
    permission_preset: str | None = None
    if preset_raw is not None:
        from ci2lab.security.opencode_presets import normalize_permission_preset

        permission_preset = normalize_permission_preset(str(preset_raw))

    limits_raw = raw.get("limits")
    bash_timeout: int | None = None
    max_output: int | None = None
    if limits_raw is not None:
        if not isinstance(limits_raw, dict):
            raise ValueError("security.limits must be an object.")
        if "bash_timeout_seconds" in limits_raw:
            bash_timeout = int(limits_raw["bash_timeout_seconds"])
        if "max_tool_output_chars" in limits_raw:
            max_output = int(limits_raw["max_tool_output_chars"])

    return SecurityConfig(
        profile=profile,
        engine=engine,
        bash_timeout_seconds=bash_timeout,
        max_tool_output_chars=max_output,
        permission=permission,
        permission_preset=permission_preset,
    )


def _merge_permission_layer(
    base: dict[str, Any],
    layer: Mapping[str, Any],
) -> dict[str, Any]:
    """Overlay ``layer`` onto ``base``, shallow-merging nested dict values."""
    merged = dict(base)
    for key, value in layer.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def merge_opencode_permission_sources(
    *layers: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """
    Merges OpenCode-style permission layers (order: the first layer wins least).

    Typical precedence: preset < permission (root) < security.permission.
    Used with opencode_experimental and claude_experimental.
    """
    merged: dict[str, Any] = {}
    for layer in layers:
        if not layer:
            continue
        merged = _merge_permission_layer(merged, layer)
    return merged


def resolved_opencode_permissions(
    config: SecurityConfig,
    *,
    root_permission: Mapping[str, Any] | None = None,
) -> OpenCodePermissionConfig:
    """Resolve the effective OpenCode permission config for ``config``.

    Args:
        config: The security configuration whose preset and permission layer
            contribute to the result.
        root_permission: Optional root-level permission mapping merged between
            the preset and ``config.permission``.

    Returns:
        The parsed :class:`OpenCodePermissionConfig`; the default experimental
        config when no layers contribute any permissions.
    """
    from ci2lab.security.opencode_presets import preset_permissions

    preset_layer: dict[str, Any] | None = None
    if config.permission_preset:
        preset_layer = preset_permissions(config.permission_preset)
    merged = merge_opencode_permission_sources(
        preset_layer,
        root_permission,
        config.permission or None,
    )
    if merged:
        return parse_opencode_permissions(merged)
    return OpenCodePermissionConfig.default_experimental()


def is_tool_blocked_by_profile(profile: str, tool_name: str) -> bool:
    """Return ``True`` if ``tool_name`` is disabled by ``profile``.

    Args:
        profile: The active security profile name.
        tool_name: The tool whose availability is being checked.

    Returns:
        ``True`` if the profile blocks the tool, ``False`` otherwise.
    """
    blocked = _PROFILE_BLOCKED_TOOLS.get(profile, frozenset())
    return tool_name in blocked


def profile_block_message(tool_name: str, profile: str) -> str:
    """Build the error message shown when a profile blocks a tool.

    Args:
        tool_name: The blocked tool's name.
        profile: The profile that blocked it.

    Returns:
        A human-readable error string describing the block.
    """
    return f"Error: TOOL_BLOCKED_BY_SECURITY_PROFILE: {tool_name} is disabled in {profile} mode"
