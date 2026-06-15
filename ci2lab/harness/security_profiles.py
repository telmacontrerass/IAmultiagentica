"""Perfiles de seguridad configurables (sin relajar garantías base)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from ci2lab.security.opencode_permissions import OpenCodePermissionConfig, parse_opencode_permissions

SECURITY_PROFILE_BLOCKED_OUTCOME = "blocked_by_security_profile"

VALID_PROFILES = frozenset({"strict", "standard", "dev", "audit"})
DEFAULT_PROFILE = "standard"

# Herramientas bloqueadas por perfil (solo endurecimiento; nunca relaja workspace/secretos).
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
    bash_timeout_seconds: int
    max_tool_output_chars: int


@dataclass(frozen=True)
class SecurityConfig:
    profile: str = DEFAULT_PROFILE
    engine: str = "claude_experimental"
    bash_timeout_seconds: int | None = None
    max_tool_output_chars: int | None = None
    permission: dict[str, Any] = field(default_factory=dict)
    permission_preset: str | None = None
    """Preset OpenCode (opencode_experimental / claude_experimental)."""

    def resolved_limits(self) -> SecurityLimits:
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
    """Perfil de seguridad no reconocido."""


def validate_profile(profile: str) -> str:
    normalized = profile.strip().lower()
    if normalized not in VALID_PROFILES:
        names = ", ".join(sorted(VALID_PROFILES))
        raise UnknownSecurityProfileError(
            f"Perfil de seguridad desconocido: {profile!r}. "
            f"Valores validos: {names}."
        )
    return normalized


def parse_security_config(raw: Mapping[str, Any] | None) -> SecurityConfig:
    if not raw:
        return SecurityConfig()
    if not isinstance(raw, dict):
        raise ValueError("security debe ser un objeto JSON/YAML.")

    profile = validate_profile(str(raw.get("profile", DEFAULT_PROFILE)))

    from ci2lab.security.engine import DEFAULT_SECURITY_ENGINE, normalize_security_engine

    engine = normalize_security_engine(str(raw.get("engine", DEFAULT_SECURITY_ENGINE)))

    permission_raw = raw.get("permission")
    permission: dict[str, Any] = {}
    if permission_raw is not None:
        if not isinstance(permission_raw, dict):
            raise ValueError("security.permission debe ser un objeto.")
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
            raise ValueError("security.limits debe ser un objeto.")
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
    Fusiona capas permission estilo OpenCode (orden: primera capa gana menos).

    Precedencia típica: preset < permission (root) < security.permission.
    Usado con opencode_experimental y claude_experimental.
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
    blocked = _PROFILE_BLOCKED_TOOLS.get(profile, frozenset())
    return tool_name in blocked


def profile_block_message(tool_name: str, profile: str) -> str:
    return (
        f"Error: TOOL_BLOCKED_BY_SECURITY_PROFILE: {tool_name} is disabled "
        f"in {profile} mode"
    )
